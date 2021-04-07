FROM bitnami/minideb:latest as kubectl_builder
WORKDIR /app
RUN install_packages curl ca-certificates upx;
RUN set -eux; \
    KUBECTL_LATEST_VERSION=$(curl -fSL https://storage.googleapis.com/kubernetes-release/release/stable.txt); \
    curl -fSLO "https://storage.googleapis.com/kubernetes-release/release/${KUBECTL_LATEST_VERSION}/bin/linux/amd64/kubectl"; \
    curl -fSL -o "kubectl.LICENSE" "https://raw.githubusercontent.com/kubernetes/kubectl/master/LICENSE"; \
    chmod +x kubectl; \
    # upx may exit with statuses like AlreadyPackedException CantPackException
    upx kubectl || true;

FROM gcr.io/distroless/python3-debian10:latest

WORKDIR /app
ENV PATH /app:$PATH
USER nonroot

COPY --from=kubectl_builder /app/* ./
COPY seoperator2.py ./

ENTRYPOINT ["/usr/bin/python3", "-u"]
CMD ["seoperator2.py"]
