# MinIO withdrew its community container images. Build the same pinned release from source.
FROM golang:1.23.4-alpine3.21 AS build
ENV CGO_ENABLED=0 GOMAXPROCS=2 GOMEMLIMIT=768MiB
WORKDIR /source
ADD https://codeload.github.com/minio/minio/tar.gz/e1f26f7c8e7f06abfe1bc6c4023f6012e1d0aa9f /tmp/source.tar.gz
RUN echo "b33290f7078d81a029a62aebe10a07aeb005ae349f5854fd52c656c324a6de3e  /tmp/source.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/source.tar.gz --strip-components=1 \
    && go build -p 1 -trimpath -ldflags="-s -w" -o /out/minio .

FROM alpine:3.21.3
COPY --from=build /out/minio /usr/local/bin/minio
COPY --from=build /source/LICENSE /licenses/LICENSE
COPY --from=build /source/CREDITS /licenses/CREDITS
ENTRYPOINT ["minio"]
