FROM bitnami/minideb:latest as base_builder
RUN mkdir -p /app;
RUN install_packages curl ca-certificates;
RUN install_packages python3 python3-pip python3-dev;
RUN install_packages build-essential upx;
RUN pip3 install https://github.com/pyinstaller/pyinstaller/tarball/develop;

FROM base_builder as kubectl_builder
RUN set -eux; \
    cd /app; \
    KUBECTL_LATEST_VERSION=$(curl -fSL https://storage.googleapis.com/kubernetes-release/release/stable.txt); \
    curl -fSLO "https://storage.googleapis.com/kubernetes-release/release/${KUBECTL_LATEST_VERSION}/bin/linux/amd64/kubectl"; \
    chmod +x kubectl; \
    # upx may exit with statuses like AlreadyPackedException CantPackException
    upx kubectl || true;

FROM base_builder as app_builder
ADD seoperator2.py /app/seoperator2.py
RUN set -eux; \
    cd /app; \
    pyinstaller --onedir seoperator2.py;

FROM gcr.io/distroless/base-debian10:latest
COPY --from=kubectl_builder /app/kubectl /usr/local/bin/kubectl
COPY --from=app_builder /app/dist/seoperator2 /app/seoperator2
# fix: libgcc_s.so.1 must be installed for pthread_cancel to work
COPY --from=base_builder /lib/x86_64-linux-gnu/libgcc_s.so.1 /app/seoperator2/libgcc_s.so.1
ENV LD_LIBRARY_PATH /app/seoperator2:$LD_LIBRARY_PATH
CMD ["/app/seoperator2/seoperator2"]
