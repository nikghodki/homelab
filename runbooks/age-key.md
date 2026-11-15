# The fleet age key (SOPS)

Everything under `secrets/` is encrypted with SOPS for one age key.

| | |
|---|---|
| Public key (recipient) | in `.sops.yaml` |
| Private key | dgx-1 `~/.config/sops/age/keys.txt` (mode 0600), plus the two offline copies below |
| Never | in GitHub, in CI, in chat, on the work laptop |

## Offline copies (do once, and after every rotation)

1. On dgx-1, in your own terminal: `cat ~/.config/sops/age/keys.txt`.
2. Save the full file contents (both the comment lines and the `AGE-SECRET-KEY-1…` line) in your password manager
   as "homelab age key".
3. Print it or write it on paper and keep it with your important documents.

## Using it

```bash
sops secrets/<name>.enc.yaml           # create or edit (opens $EDITOR, saves encrypted)
sops -d secrets/<name>.enc.yaml        # print decrypted (only on dgx-1)
```

Inside the cluster, decryption happens in Argo CD (plan P3.4); the key is loaded as a Kubernetes secret by hand,
once, from dgx-1.

## Restore (dgx-1 lost)

1. Copy the key from the password manager to `~/.config/sops/age/keys.txt` on the new machine; `chmod 600`.
2. `sops -d secrets/canary.enc.yaml` must print `canary: homelab-sops-ok`.

## Rotation (yearly, or at once if the key may have leaked)

1. `age-keygen -o new-keys.txt`, then put the new public key in `.sops.yaml`.
2. `sops updatekeys secrets/*` with both keys present, so every file is re-encrypted for the new key.
3. Rotate every secret the old key could decrypt.
4. Replace the offline copies; delete the old key.
