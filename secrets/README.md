# secrets

Only SOPS-encrypted files (age). CI fails on any plaintext file here. The age private key never leaves the home
network and is never stored in GitHub. See [runbooks/age-key.md](../runbooks/age-key.md). `canary.enc.yaml` proves decryption works.
