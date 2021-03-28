FROM bitnami/minideb:latest as base_builder

RUN set -eux; \
    mkdir -p /app; \
    cd /app; \
    install_packages curl ca-certificates;

FROM base_builder as kubectl_builder

RUN set -eux; \
    cd /app; \
    KUBECTL_LATEST_VERSION=$(curl -fSL https://storage.googleapis.com/kubernetes-release/release/stable.txt); \
    curl -fSLO "https://storage.googleapis.com/kubernetes-release/release/${KUBECTL_LATEST_VERSION}/bin/linux/amd64/kubectl"; \
    chmod +x kubectl;

FROM base_builder as jq_builder

RUN set -eux; \
    cd /app; \
    JQ_LATEST_VERSION="1.6"; \
    curl -fSL -o jq "https://github.com/stedolan/jq/releases/download/jq-${JQ_LATEST_VERSION}/jq-linux64"; \
    chmod +x jq;

FROM gcr.io/distroless/python3-debian10:latest

COPY --from=kubectl_builder /app/kubectl /usr/local/bin/kubectl
COPY --from=jq_builder /app/jq /usr/local/bin/jq

ADD seoperator2.py /app/seoperator2.py

WORKDIR /app
ENTRYPOINT ["python3", "-u"]
CMD ["seoperator2.py"]
