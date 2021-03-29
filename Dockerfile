FROM bitnami/minideb:latest as base_builder
RUN set -eux; \
    mkdir -p /app; \
    cd /app; \
    install_packages curl ca-certificates upx python3 python3-pip python3-dev binutils; \
    pip3 install pyinstaller;

FROM base_builder as kubectl_builder
RUN set -eux; \
    cd /app; \
    KUBECTL_LATEST_VERSION=$(curl -fSL https://storage.googleapis.com/kubernetes-release/release/stable.txt); \
    curl -fSLO "https://storage.googleapis.com/kubernetes-release/release/${KUBECTL_LATEST_VERSION}/bin/linux/amd64/kubectl"; \
    chmod +x kubectl; \
    # upx may exit with statuses like AlreadyPackedException CantPackException
    upx kubectl || true;

FROM base_builder as jq_builder
RUN set -eux; \
    cd /app; \
    JQ_LATEST_VERSION="1.6"; \
    curl -fSL -o jq "https://github.com/stedolan/jq/releases/download/jq-${JQ_LATEST_VERSION}/jq-linux64"; \
    chmod +x jq;  \
    # upx may exit with statuses like AlreadyPackedException CantPackException
    upx jq || true;

FROM base_builder as app_builder
ADD seoperator2.py /app/seoperator2.py
RUN set -eux; \
    cd /app; \
    pyinstaller --onedir seoperator2.py;

FROM gcr.io/distroless/base-debian10:latest
COPY --from=kubectl_builder /app/kubectl /usr/local/bin/kubectl
COPY --from=jq_builder /app/jq /usr/local/bin/jq
COPY --from=app_builder /app/dist/seoperator2 /app/seoperator2
ENV LD_LIBRARY_PATH /app/seoperator2:$LD_LIBRARY_PATH
CMD ["/app/seoperator2/seoperator2"]
