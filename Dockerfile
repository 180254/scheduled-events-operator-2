FROM bitnami/minideb:latest as kubectl_builder
WORKDIR /app
SHELL ["/bin/bash" ,"-c"]
RUN install_packages curl ca-certificates;
# https://kubernetes.io/docs/setup/release/version-skew-policy/#kubectl
# Supported minor version skew between client and server is +/-1.
ENV KUBECTL_VERSION "v1.21.3"
RUN set -Eeuxo pipefail; \
    curl -fSLO "https://storage.googleapis.com/kubernetes-release/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"; \
    curl -fSL -o "kubectl.LICENSE" "https://raw.githubusercontent.com/kubernetes/kubectl/kubernetes-${KUBECTL_VERSION//v/}/LICENSE"; \
    chmod +x kubectl;

FROM gcr.io/distroless/python3-debian10:latest
WORKDIR /app
ENV PATH /app:$PATH
USER nonroot
COPY --from=kubectl_builder /app/* ./
COPY seoperator2.py ./
ENTRYPOINT ["/usr/bin/python3", "-u"]
CMD ["seoperator2.py"]
