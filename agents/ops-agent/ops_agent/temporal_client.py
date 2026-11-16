"""Temporal client with the ops-agent certificate (namespace ops-agent writer only; runbooks/temporal.md)."""
from __future__ import annotations

from pathlib import Path

from temporalio.client import Client, TLSConfig

from .config import settings


async def connect() -> Client:
    s = settings()
    d = Path(s.temporal_tls_dir)
    tls = TLSConfig(server_root_ca_cert=(d / "ca.crt").read_bytes(), domain="temporal",
                    client_cert=(d / "tls.crt").read_bytes(), client_private_key=(d / "tls.key").read_bytes())
    return await Client.connect(s.temporal_address, namespace=s.temporal_namespace, tls=tls)
