import oci
import json
import base64
import sys
import os
import tempfile
import atexit
from datetime import datetime
from flask import Flask, request, jsonify
# --- Configuration ---
# NOTE: 1. REPLACE THE VALUES BELOW WITH YOUR ACTUAL OCI details
OCI_QUEUE_OCID = os.environ.get("OCI_QUEUE_OCID", "default-queue-ocid")
QUEUE_SERVICE_ENDPOINT = os.environ.get("QUEUE_SERVICE_ENDPOINT", "https://cell-1.queue.messaging.region.oci.oraclecloud.com")

OCI_TENANCY_OCID = os.environ.get("OCI_TENANCY_OCID")
OCI_USER_OCID = os.environ.get("OCI_USER_OCID")
OCI_FINGERPRINT = os.environ.get("OCI_FINGERPRINT")
OCI_REGION = os.environ.get("OCI_REGION")
OCI_PRIVATE_KEY_CONTENT = os.environ.get("OCI_PRIVATE_KEY_CONTENT")
# --- OCI Client Setup Function ---
def create_oci_client():
    """
    Initializes the OCI Queue client.
    Switches logic based on environment: Kubernetes Secret (Env Vars) or Local Config File.
    """

    # Check if running inside Kubernetes (K8s Service Host is standard for K8s pods)
    is_running_in_k8s = os.environ.get('KUBERNETES_SERVICE_HOST') is not None
    if is_running_in_k8s:
        # 1. Kubernetes Mode: Use credentials injected from Secret
        if not all([OCI_TENANCY_OCID, OCI_USER_OCID, OCI_FINGERPRINT, OCI_PRIVATE_KEY_CONTENT, OCI_REGION]) or OCI_QUEUE_OCID == "default-queue-ocid":
            print("[CRITICAL ERROR] K8S mode detected, but OCI Secret variables are missing. Required: OCI_TENANCY_OCID, OCI_USER_OCID, OCI_FINGERPRINT, OCI_PRIVATE_KEY_CONTENT, OCI_REGION, OCI_QUEUE_OCID.", file=sys.stderr)
            return None

        print("[INFO] Attempting OCI client initialization using Kubernetes Secret variables.")
        try:
            # Save the private key content to a temporary file
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_key_file:
                temp_key_file.write(OCI_PRIVATE_KEY_CONTENT)
                private_key_temp_path = temp_key_file.name

            # Register cleanup function to delete the temp file when the process exits
            atexit.register(lambda: os.remove(private_key_temp_path) if private_key_temp_path and os.path.exists(private_key_temp_path) else None)

            # The OCI config now points to the path of the temporary key file
            config = {
                "user": OCI_USER_OCID,
                "key_file": private_key_temp_path, # <-- CORRECTED: Points to the temp file path
                "fingerprint": OCI_FINGERPRINT,
                "tenancy": OCI_TENANCY_OCID,
                "region": OCI_REGION
            }


        except Exception as e:
            print(f"[FATAL ERROR] Error processing key file from Secret data: {e}", file=sys.stderr)
            return None

    else:
        # 2. Local Mode: Use the default local configuration file (~/.oci/config)
        print("[INFO] Local mode detected. Attempting OCI client initialization using ~/.oci/config.")
        try:
            if OCI_QUEUE_OCID == "default-queue-ocid":
                 print("[ERROR] Local run requires OCI_QUEUE_OCID environment variable to be set.", file=sys.stderr)
                 return None

            # Use the user's preferred direct config loading method
            config = oci.config.from_file("~/.oci/config", "DEFAULT")

        except Exception as e:
            print(f"[FATAL ERROR] Failed to initialize OCI client using local config: {e}", file=sys.stderr)
            print("Ensure you have a valid ~/.oci/config file and the 'DEFAULT' profile is configured.", file=sys.stderr)
            return None

    # Common initialization step
    try:
        queue_client = oci.queue.QueueClient(config, service_endpoint=QUEUE_SERVICE_ENDPOINT)
        print("[INFO] OCI Queue client initialized successfully.")
        return queue_client
    except Exception as e:
        print(f"[FATAL ERROR] Failed to create OCI Queue Client: {e}", file=sys.stderr)
        return None

# Initialize the client globally
queue_client = create_oci_client()


from oci.queue.models import (
    PutMessagesDetails, 
    PutMessagesDetailsEntry, 
    MessageMetadata
)

# Initialize Flask App
app = Flask(__name__)

# Default OQS fields (used in payload transformation)
DEFAULT_FAMILY = "resource"
DEFAULT_MODEL_VERSION = "v1"
DEFAULT_CHANNEL = "info" # Used as a fallback

# -----------------------------
# Function to send a message to OCI Queue
# -----------------------------
def send_message(payload: dict, channel_id: str, key: str) -> dict:
    """
    Sends a single message to the OCI Queue using the correct put_messages method
    and includes channel/key metadata.
    """
    try:
        # 1. Prepare Metadata
        metadata = MessageMetadata(
            channel_id=channel_id,
            custom_properties={"key": key}
        )
        
        # 2. Prepare the Content (JSON encoded, then Base64 encoded, which OCI Queue requires)
        json_content = json.dumps(payload).encode('utf-8')
        encoded_content = base64.b64encode(json_content).decode('utf-8')
        
        # 3. Create the PutMessagesDetailsEntry
        entry = PutMessagesDetailsEntry(
            content=encoded_content,
            metadata=metadata
        )

        # 4. Create the request details and send using the correct put_messages method
        details = PutMessagesDetails(messages=[entry])

        resp = queue_client.put_messages(
            queue_id=OCI_QUEUE_OCID,
            put_messages_details=details
        )
        
        # 5. Process the result using the attribute name found previously to work
        result = resp.data.messages[0] 

        
        return {
            "status": "SUCCESS",
            "message_id": result.id,
        }

    except oci.exceptions.ServiceError as e:
        print(f"[OCI Service Error] Code={e.code}, Message='{e.message}'", file=sys.stderr)
        return {"status": "ERROR", "message": f"OCI Service Error: {e.code}"}
        
    except Exception as e:
        # Catch-all ensures a dictionary is always returned
        print(f"[Unexpected Error in send_message] {e}", file=sys.stderr)
        return {"status": "ERROR", "message": str(e)}

# -----------------------------
# Flask Route for Alertmanager Webhook
# -----------------------------
@app.route("/anomaly", methods=["POST"])
def receive_alerts():
    if not request.json:
        return jsonify({"status": "error", "message": "Invalid JSON payload"}), 400

    payload = request.json
    alerts = payload.get("alerts", [])
    all_responses = []

    for alert in alerts:
        alert_name = alert.get("labels", {}).get("alertname", "unknown_alert")
        
        try:
            # 1. Transform Alertmanager alert → OQS message schema
            oqs_payload = {
                "alertname": alert.get("labels", {}).get("alertname", "unknown"),
                "app": alert.get("labels", {}).get("app", "unknown"),
                "bastion": alert.get("labels", {}).get("bastion", "unknown"),
                "cluster": alert.get("labels", {}).get("cluster", "unknown"),
                "kubernetes_namespace": alert.get("labels", {}).get("kubernetes_namespace", "unknown"),
                "kubernetes_pod_name": alert.get("labels", {}).get("kubernetes_pod_name", "unknown"),
                "namespace": alert.get("labels", {}).get("namespace", "unknown"),
                "oid": alert.get("labels", {}).get("oid", "unknown"),
                "pod_template_hash": alert.get("labels", {}).get("pod_template_hash", "unknown"),
                "prometheus": alert.get("labels", {}).get("prometheus", "unknown"),
                "job": alert.get("labels", {}).get("job", "unknown"),
                "instance": alert.get("labels", {}).get("instance", "unknown"),
                "region": alert.get("labels", {}).get("region", "unknown"),
                "query_name": alert.get("labels", {}).get("query_name", "unknown"),
                "query": alert.get("labels", {}).get("query", "unknown"),
                "model": alert.get("labels", {}).get("model", "unknown"),
                "context": alert.get("labels", {}).get("context", "unknown"),
                "anomaly_last_timestamp": alert.get("labels", {}).get("anomaly_last_timestamp", "unknown"),
                "anomaly_value_last": alert.get("labels", {}).get("anomaly_value_last", "unknown"),
                "source": alert.get("labels", {}).get("source", "alertmanager"),
                "severity": alert.get("labels", {}).get("severity", DEFAULT_CHANNEL),
                "queue": OCI_QUEUE_OCID,
                "channel": "alert-critical",
                "evaluated_at": alert.get("startsAt", datetime.utcnow().isoformat() + "Z"),
                "fingerprint": alert.get("fingerprint", "unknown")
            }

            # 2. Define channel_id and key_value for queue
            channel_id = f"alert-critical"
            key_value = alert.get("fingerprint", alert_name)

            # 3. Publish the message
            response = send_message(payload=oqs_payload, channel_id=channel_id, key=key_value)
            
            # Since send_message is guaranteed to return a dictionary, we skip the 'response is None' check
            # and rely on the dictionary contents.

            all_responses.append({
                "alert": alert_name,
                "channel": channel_id,
                "result": response["status"],
                "details": response.get("message_id") or response.get("message")
            })

        except Exception as e:
            # Catch errors during payload transformation or other unexpected flow issues
            print(f"Error processing alert {alert_name}: {e}", file=sys.stderr)
            all_responses.append({
                "alert": alert_name,
                "channel": "unknown",
                "result": "FATAL_ERROR",
                "details": f"Alert processing failed: {str(e)}"
            })

    print(f"Processed {len(all_responses)} alerts. Statuses: {[r['result'] for r in all_responses]}")

    # Return a 200 OK with processing details
    return jsonify({"results": all_responses}), 200

# -----------------------------
# Run Flask
# -----------------------------
if __name__ == "__main__":
    print(f"OCI Queue Publisher Webhook starting on port 8000...")
    
    # --- Local TLS Setup for Dev (Requires 'cert.pem' and 'key.pem') ---
    ssl_context = None
    if os.path.exists("cert.pem") and os.path.exists("key.pem"):
        print("[INFO] Found cert.pem and key.pem. Running with HTTPS on port 5000.")
        ssl_context = ("cert.pem", "key.pem")
    else:
        print("[INFO] Running with HTTP on port 5000 (Insecure for production).")

    # NOTE: Remember to use Gunicorn in production!
    app.run(host="0.0.0.0", port=5000, ssl_context=ssl_context)
