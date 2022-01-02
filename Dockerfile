FROM bitnami/minideb:latest as kubectl_builder
WORKDIR /app
SHELL ["/bin/bash" ,"-c"]
RUN install_packages curl ca-certificates;
# https://kubernetes.io/docs/setup/release/version-skew-policy/#kubectl
# Supported minor version skew between client and server is +/-1.
ENV KUBECTL_VERSION "v1.23.1"
RUN set -Eeuxo pipefail; \
    curl -fSLO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"; \
    curl -fSLO "https://dl.k8s.io/${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256"; \
    curl -fSL -o "kubectl.LICENSE" "https://raw.githubusercontent.com/kubernetes/kubectl/kubernetes-${KUBECTL_VERSION//v/}/LICENSE"; \
    echo "$(<kubectl.sha256) kubectl" | sha256sum --check; \
    chmod +x kubectl;

FROM gcr.io/distroless/python3-debian11:latest
WORKDIR /app
ENV PATH /app:$PATH
USER nonroot
COPY --from=kubectl_builder /app/* ./
COPY seoperator2.py ./
ENTRYPOINT ["/usr/bin/python3", "-u"]
CMD ["seoperator2.py"]
