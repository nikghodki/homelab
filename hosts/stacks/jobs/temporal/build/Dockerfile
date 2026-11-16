# Temporal server 1.32.2 with one patch: a claim mapper that takes Temporal roles from the client certificate's URI
# SANs (tlsclaims.go, main.go.patch; runbooks/temporal.md "mTLS and authorization"). Upstream only maps JWT claims.
# Built on dgx-2 by compose (like the ml stack's mlflow); bump the image tag in compose.yaml when anything here changes.
# The arm64 build of the whole server under QEMU would take most of a GitHub-hosted run (decision 0008), so it isn't
# in build-sign.yml; this stack runs in Docker, outside Kyverno.
FROM golang:1.26.10-alpine@sha256:87c65a688975c0b1d4585d204874c45ca78354670e3a5f11368c5a492303d696 AS build
RUN apk add --no-cache git
ARG TEMPORAL_TAG=v1.32.2
ARG TEMPORAL_COMMIT=6d085822273f4336796e6959c73ab1d14a23eb77
RUN git clone --quiet --depth 1 --branch "$TEMPORAL_TAG" https://github.com/temporalio/temporal.git /src \
 && test "$(git -C /src rev-parse HEAD)" = "$TEMPORAL_COMMIT"
WORKDIR /src
# Modules in their own (cached) layer, with retries: a DNS hiccup on the LAN shouldn't fail a deploy.
RUN for i in 1 2 3 4 5; do go mod download && exit 0; echo "go mod download failed (attempt $i)"; sleep $((i * 10)); done; exit 1
COPY main.go.patch /tmp/main.go.patch
COPY tlsclaims.go tlsclaims_test.go cmd/server/
RUN git apply /tmp/main.go.patch
# Same build as upstream's Makefile (CGO off, tag disable_grpc_modules); the test runs the mapper and the default
# authorizer together.
RUN CGO_ENABLED=0 go test -tags disable_grpc_modules -run TestTLSURIClaims ./cmd/server/ \
 && CGO_ENABLED=0 go build -tags disable_grpc_modules -trimpath -o /out/temporal-server ./cmd/server

FROM temporalio/server:1.32.2@sha256:7bf69188a6232fea14869b9cef3d94aa82a1601d99517f7e86c71f22da4e0670
COPY --from=build --chmod=755 /out/temporal-server /usr/local/bin/temporal-server
