# Model supply chain: provenance and pickle checks for DGXMM downloads

Design note for plan P2.5 ("ModelScan/picklescan in DGXMM's download step; approval for remote-code models").
Nothing here is implemented in DGXMM yet: the DGXMM session owns that code. Read from dgx-1
`~/workspace/dgx-model-manager` at commit `453c021` (2026-11-15), read-only.

## How DGXMM gets weights today

| Path | Code | What it checks |
|---|---|---|
| Hub download (UI / API) | `dgxmm/downloads.py` `DownloadService.start` → `_run` | Repo id and revision validated; revision pinned to the Hub commit sha when queued; by default only `DEFAULT_PATTERNS` (`*.safetensors`, `*.json`, tokenizer files, `*.py`, `*.txt`, `*.md` ...) minus `EXCLUDE` (`*.bin`, `*.pt`, `*.pth`, `*.h5`, `*.msgpack`, `*.onnx`, `*.gguf`, `original/*`). Each file is fetched by `hf_hub_download` in a `python -I` child into the HF cache (`~/.cache/huggingface`, 313 GB today). |
| Decision models (`DECIDER_MODELS`) | `dgxmm/decider/snapshot.py` | Pinned revision, every file's SHA-256 from a hash list baked into the repo, checked before it is linked. Already the target state; no change needed. |
| GGUF files | `~/models` (`gguf_roots`, 461 GB today), placed by hand or with an explicit `include` | llama.cpp engine parses the GGUF header (`engines/llamacpp.py`). |
| Engine start | `engines/vllm.py` | `HF_HUB_OFFLINE=1`, so an engine never fetches weights itself. `trust_remote_code` is off unless chosen; `decider/remote_code.py` + `code_scan.py` triage the repo's `*.py` when it would be enabled (informational, never blocks). |

Gaps that matter for P2.5:

1. **`include` skips `EXCLUDE`.** With explicit patterns (`start(..., include=[...])`) the pickle-capable formats are
   downloaded as asked: `*.bin`, `*.pt`, `*.pth` are pickles, so loading one can run code.
2. **No content check of any file.** A `.safetensors` file is trusted by its name; a GGUF only by a header parse.
3. **No provenance.** Nothing compares what a repo claims to be (card / `config.json` base model) with what the
   weights are. Fine-tunes and re-uploads of popular models are the usual way a tampered model is distributed.
4. **Hand-placed GGUFs and the existing cache** never pass through the download step.

## Where the checks plug in

The download already has a quarantine: while it runs, the repo dir holds `DOWNLOAD_MARKER` and the inventory reports
the snapshot as incomplete, so it cannot be deployed. `_run` removes the marker only after the last file, then
refreshes the inventory and sets `state="done"`. The checks go **between the last file and `_clear_marker`**:

```
_run: files fetched ──► [1 format gate] ──► [2 content scan] ──► _clear_marker ──► inventory.refresh ──► done
                              │ fail             │ fail                                   │
                              └──────────────────┴──► state="failed", marker kept,        └──► [3 provenance, async]
                                                     reason shown on the Downloads page          result shown, logged
```

| # | Check | Tool | Blocks? | Cost |
|---|---|---|---|---|
| 1 | Format gate: refuse pickle-capable files (`*.bin`, `*.pt`, `*.pth`, `*.pkl`, `*.ckpt`, `*.joblib`, `*.npy` with objects) also when they come in through `include`; admin override per download, recorded in the audit log | DGXMM code (allow-list it already has) | yes | none |
| 2a | Pickle scan of any pickle-capable file that got through the override | picklescan or ModelScan (both static: they read opcodes, never unpickle) | yes, on a dangerous import/global | seconds |
| 2b | safetensors header check: JSON header parses, dtypes/shapes/offsets consistent, no data outside the tensors | small DGXMM function (no dependency) | yes | milliseconds |
| 2c | GGUF metadata check: header and KV types parse (DGXMM already does this); flag a Jinja chat template with code-like constructs for review | DGXMM | review flag | milliseconds |
| 3 | Provenance: `provenancekit scan <snapshot path> --json` against the bundled reference DB (~175 base models, 45+ families) plus the deep-signal weight fingerprints (`provenancekit download-deepsignals-fingerprint`, HF dataset `cisco-ai/model-provenance-kit`). Compare the detected family with the repo's claimed base model; a mismatch or "no known base" is a review flag on the model, not a block | model-provenance-kit 1.2.0 (GitHub release; not on PyPI), own venv, `--trust-remote-code` never passed | no (flag + log to Loki) | reads all weights; streams models over 20 GB; minutes per model |
| 4 | Remote code: keep the existing triage, make enabling `trust_remote_code` an explicit approval (P2.5's second half) | DGXMM | approval | — |

Checks 1 and 2 are synchronous and cheap, so a refused file never becomes a deployable model ("a test pickle with
code is refused" is P2.5's acceptance test). Check 3 is slow and advisory, so it runs after the download completes,
in the background, and its verdict is stored next to the inventory entry.

### What runs where

| Job | Host | Why |
|---|---|---|
| Checks 1, 2 | the host that downloads (dgx-1 today; dgx-2 once it runs its own DGXMM, P2.1) | Must run before the marker is cleared; weights are not copied between hosts. |
| Check 3 (new downloads) | same host, `nice`/`ionice`, one at a time, memory-capped | Needs the weights; dgx-1's unified memory is shared with the engines, so it must stay small and yield. |
| Check 3 backfill of the existing 313 GB HF cache and 461 GB of GGUFs | dgx-2 (more headroom: batch, observability) over a read-only NFS/sshfs mount of dgx-1's model dirs, or on dgx-1 at night | One-off; GGUF coverage depends on the kit (its README covers HF-format checkpoints, so GGUFs may only get the metadata signals). |
| Scanner self-test with **pickle-fuzzer** | dgx-2 or GitHub Actions (it ships an Action) | pickle-fuzzer **generates** valid, odd pickles to test pickle *parsers and scanners*; it does not scan models. Weekly: feed its output plus a small set of known-malicious seeds into the chosen scanner (2a); fail if the scanner crashes, hangs, or passes a malicious seed. |

## Deferred until the DGXMM session is done

- Every change in `dgxmm/downloads.py` (gate between the last file and `_clear_marker`, `EXCLUDE` for `include`,
  the `failed` reason, the admin override and its audit entry) and the UI for it.
- The `trust_remote_code` approval flow.
- Provenance wiring (background job, stored verdict, Loki line) and the backfill.
- DGXMM on dgx-2 (P2.1), which decides where dgx-2's checks run.

Can be done before, without touching DGXMM: choose picklescan vs ModelScan, and build the pickle-fuzzer self-test
for it on dgx-2; pin model-provenance-kit in its own hash-locked venv and try it on two models by hand.

Related: the Cisco AIBOM fleet job (runbooks/aibom.md) already inventories DGXMM's code and the model references in
it, but not the weights; decisions/0003-cisco-ai-defense-tools.md lists every Cisco AI Defense tool and its status.
