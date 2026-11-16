# cisco-aibom 1.10.1: `MLLifecycleDetector` re-searches the whole file for every line of a Python file (quadratic)

Target: github.com/cisco-ai-defense/aibom

## Upstream check (2026-11-16)

- Issues searched: `slow`, `performance`, `ml_lifecycle`. Nothing reports it.
- `main` still has it: `aibom/src/aibom/scanners/ml_lifecycle_detector.py:584-585`. The latest release is 1.10.1
  (2026-11-04). Status: **not reported, not fixed.**

## Version and environment

cisco-aibom 1.10.1 (PyPI, `.github/requirements-aibom.txt`), Python 3.12, `analyze <dir>`; DGX Spark (GB10, aarch64)
and Jetson Orin.

## Steps to reproduce

```bash
git clone https://github.com/NousResearch/hermes-agent && cd hermes-agent && git checkout 97a9ae8
cisco-aibom analyze . -o json -O /tmp/r.json --llm-model none --llm-provider openai \
  --llm-api-base http://127.0.0.1:9 --llm-api-key x --agentic-timeout 5 --agentic-max-retry-seconds 0
```

## Expected

The deterministic stage takes minutes for ~8,200 Python files (96 MB).

## Actual

About 75 minutes of one fully busy core on a DGX Spark. On a Jetson Orin it never finished inside 3 hours. py-spy
samples over 70 minutes all land in the same place:

```
MLLifecycleDetector.scan (aibom/scanners/ml_lifecycle_detector.py:585)
```

```python
for line_no, line in enumerate(scan_lines, start=1):          # every line of the file
    ...
    if is_py:
        all_hp_rules = list(_HP_RULES)
        for ctx_rx, ctx_key, ctx_guard in _HP_CONTEXT_RULES:
            if ctx_guard.search(text):                         # searches the WHOLE file, again, per line
                all_hp_rules.append((ctx_rx, ctx_key))
```

The cost per file is lines × file size × the number of context rules. Hermes' `tests/` directory alone (5,900 files,
54 MB) is about half of it, by the same measure.

## Suggested fix

The guards only depend on `text`, so compute `all_hp_rules` once per file, before the line loop.

## Our workaround

None in the scanner. The fleet job keeps cisco-aibom's cache between runs (`<state>/cache`), so an unchanged
checkout is rescanned from the cache. The Jetson's Hermes checkouts are scanned on dgx-2 with a 5 h limit per target
(runbooks/aibom.md).
