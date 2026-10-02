pipeline {
    agent any

    options {
        skipDefaultCheckout()
        disableConcurrentBuilds()
        timestamps()
    }

    parameters {
        string(name: 'KUBE_NAMESPACE', defaultValue: 'ociqueue', description: 'Namespace of the existing webhook Helm release')
        string(name: 'HELM_RELEASE', defaultValue: 'ociqueue-webhook', description: 'Existing webhook Helm release name')
    }

    environment {
        IMAGE_REPOSITORY = 'eu-frankfurt-1.ocir.io/idr1ghk373xi/ociqueue_webhook'
        OCIR_HOST = 'eu-frankfurt-1.ocir.io'
        CHART = 'webhook'
        OCI_CLI_AUTH = 'instance_principal'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                script {
                    env.IMAGE_TAG = "${env.BUILD_NUMBER}-${sh(script: 'git rev-parse --short=12 HEAD', returnStdout: true).trim()}"
                    // A Pipeline-from-SCM job checks out a detached commit, so BRANCH_NAME may be unset.
                    env.DEPLOY_FROM_MAIN = sh(
                        script: 'test "$(git rev-parse HEAD)" = "$(git rev-parse refs/remotes/origin/main)"',
                        returnStatus: true
                    ) == 0 ? 'true' : 'false'
                }
            }
        }

        stage('Agent tools') {
            steps {
                sh '''
                    set -eu
                    command -v docker >/dev/null || { echo 'Docker CLI is missing on this Jenkins node'; exit 1; }
                    command -v helm >/dev/null || { echo 'Helm is missing on this Jenkins node'; exit 1; }
                    docker info >/dev/null || { echo 'Jenkins cannot access the Docker daemon'; exit 1; }
                '''
            }
        }

        stage('Source safety') {
            steps {
                sh '''
                    set -eu
                    for file in key.pem cert.pem docker_files.zip; do
                      if git ls-files --error-unmatch "$file" >/dev/null 2>&1; then
                        echo "Remove $file from Git before building"
                        exit 1
                      fi
                    done
                    test -d "$CHART/templates" || { echo 'Helm templates directory is missing'; exit 1; }
                '''
            }
        }


        stage('Build and lint') {
            steps {
                sh '''
                    set -eu
                    helm lint "$CHART"
                    docker build -f Dockerfile \
                      -t "$IMAGE_REPOSITORY:$IMAGE_TAG" .
                '''
            }
        }

        stage('Validate deployment target') {
            when { expression { env.DEPLOY_FROM_MAIN == 'true' } }
            steps {
                script {
                    if (!params.KUBE_NAMESPACE?.trim() || !params.HELM_RELEASE?.trim()) {
                        error('Set KUBE_NAMESPACE and HELM_RELEASE to the running webhook deployment before enabling deployment.')
                    }
                }
                withCredentials([file(credentialsId: 'oke-kubeconfig', variable: 'KUBECONFIG_FILE')]) {
                    sh '''
                        set -eu
                        export KUBECONFIG="$KUBECONFIG_FILE"
                        helm status "$HELM_RELEASE" --namespace "$KUBE_NAMESPACE" >/dev/null
                    '''
                }
            }
        }

        stage('Push image') {
            when { expression { env.DEPLOY_FROM_MAIN == 'true' } }
            steps {
                withCredentials([usernamePassword(credentialsId: 'ocir-push', usernameVariable: 'OCIR_USER', passwordVariable: 'OCIR_TOKEN')]) {
                    sh '''
                        set +x
                        set -eu
                        export DOCKER_CONFIG="$(mktemp -d)"
                        export REGISTRY_AUTH_FILE="$DOCKER_CONFIG/auth.json"
                        trap 'rm -rf "$DOCKER_CONFIG"' EXIT
                        printf '%s' "$OCIR_TOKEN" | docker login "$OCIR_HOST" -u "$OCIR_USER" --password-stdin
                        docker push "$IMAGE_REPOSITORY:$IMAGE_TAG"
                    '''
                }
            }
        }

        stage('Deploy to OKE') {
            when { expression { env.DEPLOY_FROM_MAIN == 'true' } }
            steps {
                withCredentials([file(credentialsId: 'oke-kubeconfig', variable: 'KUBECONFIG_FILE')]) {
                    sh '''
                        set -eu
                        export KUBECONFIG="$KUBECONFIG_FILE"
                        helm upgrade "$HELM_RELEASE" "$CHART" \
                          --namespace "$KUBE_NAMESPACE" \
                          --reuse-values \
                          --set-string "image.repository=$IMAGE_REPOSITORY" \
                          --set-string "image.tag=$IMAGE_TAG" \
                          --atomic --wait --timeout 5m
                    '''
                }
            }
        }
    }
}
