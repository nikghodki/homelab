# MLflow tracking server for the ml stack (plan P6.5; runbooks/mlflow.md). Built on dgx-2 by compose.
# The official image has no PostgreSQL driver, so this adds psycopg2-binary (hash-pinned) and a non-root user.
FROM ghcr.io/mlflow/mlflow:v3.18.0@sha256:257204c77980b0f3450a26eb6089e487603fcdd4509529eadaf88f90669f5c13

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-deps --require-hashes -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt \
 && useradd --create-home --uid 1000 mlflow \
 && mkdir -p /mlartifacts \
 && chown 1000:1000 /mlartifacts

USER 1000:1000
WORKDIR /home/mlflow
