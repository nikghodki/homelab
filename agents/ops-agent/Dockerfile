# ghcr.io/nikghodki/ops-agent: one image for ops-ingest, ops-worker and ops-portal (decision 0013,
# runbooks/ops-agent.md). Built, signed and attested by .github/workflows/build-sign.yml; Kyverno admits it by
# signature. Dependencies are installed with hashes (requirements.txt from requirements.in, `uv pip compile
# --universal --generate-hashes`).
FROM python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# git + ssh: the change tracker reads main with a read-only deploy key
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --create-home --home-dir /var/lib/ops-agent --shell /usr/sbin/nologin ops
COPY requirements.txt /tmp/requirements.txt
RUN pip install --require-hashes --no-deps -r /tmp/requirements.txt && rm /tmp/requirements.txt
COPY pyproject.toml README.md /src/
COPY ops_agent /src/ops_agent
RUN pip install --no-deps --no-build-isolation /src || pip install --no-deps /src
USER 10001
WORKDIR /var/lib/ops-agent
ENTRYPOINT ["ops-agent"]
