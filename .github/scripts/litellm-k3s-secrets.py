#!/usr/bin/env python3
# Builds the KSOPS Secret manifests of LiteLLM in k3s from SOPS, to stdout (runbooks/litellm.md "In k3s").
# Usage, from the repo root: litellm-k3s-secrets.py litellm|redis|db | sops --encrypt --input-type yaml
#   --output-type yaml --filename-override <file> /dev/stdin > <file>. Never prints a value anywhere else.
import json, subprocess, sys
def dec(f):
    return json.loads(subprocess.run(["sops", "-d", "--output-type", "json", f], capture_output=True, text=True, check=True).stdout)
l = dec("secrets/litellm.enc.yaml"); c = dec("secrets/console.enc.yaml")
which = sys.argv[1]
def secret(name, ns, data, typ="Opaque"):
    out = [f"apiVersion: v1\nkind: Secret\nmetadata:\n  name: {name}\n  namespace: {ns}\ntype: {typ}\nstringData:"]
    for k, v in data.items():
        out.append(f"  {k}: {json.dumps(v)}")
    print("\n".join(out))
if which == "litellm":
    secret("litellm", "litellm", {
        "LITELLM_MASTER_KEY": l["litellm_master_key"], "LITELLM_SALT_KEY": l["litellm_salt_key"],
        "DATABASE_URL": f"postgresql://litellm:{l['litellm_db_password']}@10.43.0.151:5432/litellm",
        "UI_USERNAME": "nikghodki", "UI_PASSWORD": l["litellm_ui_password"],
        "DEFENSECLAW_TOKEN": l["defenseclaw_dgx1_gateway_token"], "PHOENIX_API_KEY": l["phoenix_api_key"],
        "GENERIC_CLIENT_SECRET": c["oidc_litellm_secret"], "REDIS_PASSWORD": l["litellm_redis_password"]})
elif which == "redis":
    conf = (f"requirepass {l['litellm_redis_password']}\nsave \"\"\nappendonly no\ndir /data\n"
            "maxmemory 200mb\nmaxmemory-policy volatile-lru\nloglevel warning\n")
    secret("litellm-redis", "litellm", {"redis.conf": conf})
elif which == "db":
    secret("litellm-db-app", "data", {"username": "litellm", "password": l["litellm_db_password"]}, "kubernetes.io/basic-auth")
