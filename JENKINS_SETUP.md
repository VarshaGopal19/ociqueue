# Jenkins pipeline for the OKE webhook

The `Jenkinsfile` in this folder builds `docker_files/publisher_webhook_new.py`,
lints the Helm chart, and deploys a versioned image to the **existing** Helm
release. It does not run mocked unit tests or a live OCI Queue integration test.
Only builds of the `main` branch push and deploy. Other branches run CI checks.

## Jenkins prerequisites

1. Put the contents of this `cicd` folder at the root of a Git repository, and
   create a Jenkins Multibranch Pipeline pointed at that repository. This local
   directory is not currently a Git checkout, so `checkout scm` cannot run until
   the files are in source control. The pipeline uses `docker_files/...` paths
   relative to the repository root.
2. Use an agent labeled `docker-helm-oke` with Docker, Helm 3, and any
   OCI CLI/authentication needed by its kubeconfig. The agent must reach OCIR,
   the package registries used by Docker builds, and the OKE API.
3. Add these Jenkins credentials:
   - `ocir-push`: Username with password. Username is the OCIR tenancy namespace
     plus OCI username (and identity domain, if applicable); password is an OCI
     auth token with permission to push to the image repository.
   - `oke-kubeconfig`: Secret file containing a kubeconfig that can access the
     target OKE cluster and update the existing Helm release. If it uses an OCI
     CLI exec credential, configure that identity on the Jenkins agent.
4. The job parameters default to the running webhook's namespace `ociqueue` and
   Helm release `ociqueue-webhook`. Confirm them from an OKE-connected shell with:

   ```sh
   helm list -A
   ```

   The pipeline checks `helm status` before pushing and uses `helm upgrade`, so
   it will not create a new release from an incorrect name.
5. Confirm the existing namespace has the `oci-credentials`, `webhook-tls`, and
   `webhook-secret` Kubernetes Secrets expected by the chart. Keep those values
   in Kubernetes/Jenkins credentials, not in the repository or container image.

The image repository and registry are set to the repository from
`docker_files/ociqueue_webhook/values.yaml`. Change them in the `Jenkinsfile`
if the running deployment uses a different OCIR repository. The pipeline rejects
Git-tracked local PEM files and `docker_files.zip` before building. The
`.gitignore` also excludes them when using Git. GitHub's browser upload does not
apply `.gitignore`, so select only the source, chart, `Jenkinsfile`, and
this guide if uploading through the browser. Check `git status` before the
first push from a local checkout.

`helm upgrade --reuse-values --atomic --wait` preserves existing release values
while changing the image tag. On failed readiness, Helm rolls back the release.
The pipeline does not modify the cluster until the Git repository, Jenkins
credentials, and target parameters are configured and a `main` build runs.

The original webhook returns HTTP 200 even when `send_message` reports an OCI
error. Alertmanager may treat that response as successful delivery. This behavior
is unchanged by the pipeline and should be reviewed before relying on automatic
retries.
