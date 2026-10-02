FROM container-registry.oracle.com/os/oraclelinux:9-slim

# In case it's needed the proxy
# ARG http_proxy=
# ARG https_proxy=
# ARG no_proxy=
#ENV http_proxy 'http://www-proxy.us.oracle.com:80'
#ENV https_proxy 'http://www-proxy.us.oracle.com:80' 
#ENV no_proxy 'localhost,127.0.0.1,*.oraclecorp.com,*.us.oracle.com,.alm.oraclecorp.com,alm.oraclecorp.com,.oraclecorp.com,.us.oracle.com,100.76.158.78,150.136.47.135' 

RUN microdnf update
RUN microdnf install python39
RUN microdnf install python3-pip
COPY requirements.txt /
RUN pip install --no-cache-dir -U pip
RUN pip install --no-cache-dir -r /requirements.txt

RUN microdnf update
RUN microdnf clean all
RUN microdnf install -y wget

RUN useradd -m appuser
WORKDIR /app 

# Use a non-root user for security (recommended best practice)
USER appuser
COPY --chown=appuser:appuser publisher_webhook_new.py /app/

ENV PYTHONPATH "${PYTHONPATH}:/app/src"

# In case that proxy is not needed after dowloand packages, unset proxy
# ENV HTTP_PROXY ""
# ENV http_proxy ""
# ENV HTTPS_PROXY ""
# ENV https_proxy ""
# ENV NO_PROXY ""
# ENV no_proxy ""
# RUN unset HTTP_PROXY http_proxy HTTPS_PROXY https_proxy NO_PROXY no_proxy

EXPOSE 5000

# Use python3.9 explicitly as the entry point
CMD ["gunicorn","-w", "2","-b", "0.0.0.0:5000","--certfile=/app/cert.pem","--keyfile=/app/key.pem", "publisher_webhook_new:app"]
