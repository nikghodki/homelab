# mcp-scanner 4.8.7 pins `litellm==1.93.2` (GHSA-7hp6-4w63-5g45, GHSA-g5ff-637f-6q2m): please release the relaxed pin with a safe floor

Target: github.com/cisco-ai-defense/mcp-scanner

## Upstream check (2026-11-15)

- **Partly fixed on `main`, not released.** #289 (2026-10-27) changed the exact pin to a floor:
  `litellm>=1.93.2,!=1.94.0,!=1.94.1,!=1.94.2,!=1.95.0,!=1.96.0,!=1.96.1`.
  - The floor still allows 1.93.2, which has both advisories.
  - The latest release and PyPI are still 4.8.7 with `litellm==1.93.2`.
- **Already proposed in open PRs:**
  - #290: raise the floor to 1.106.5 and cites GHSA-7hp6-4w63-5g45.
  - #295: raise the litellm and mcp floors.
  - #315 (opened 2026-11-15): raise the floor to 1.109.1.
  - #284: release 4.8.8 with relaxed pins.
- Related open issue #285: make LiteLLM optional for the YARA-only analyzers.
- Status: **fixed on main (floor only), unreleased. Don't open a new issue.** At most, add a short comment on #290 or
  #315 asking for a release, with the details below.

## Version

`cisco-ai-mcp-scanner` 4.8.7 (PyPI, 2026-10-20).

## Environment

GitHub Actions (ubuntu-24.04), Python 3.12, hash-pinned `requirements-ci.txt`, OSV-Scanner v2.7.1.

## Steps to reproduce

```bash
pip install cisco-ai-mcp-scanner==4.8.7
pip show litellm        # 1.93.2
osv-scanner scan source -r .
```

## Expected

Installing mcp-scanner doesn't pull a litellm with known advisories, and it can be installed next to a newer litellm.

## Actual

Resolution is forced to `litellm==1.93.2`. OSV reports:

- GHSA-7hp6-4w63-5g45: privilege escalation in the LiteLLM proxy. Our CI exception says it needs `litellm>=1.100.4`.
- GHSA-g5ff-637f-6q2m: file read through the proxy's `/utils/transform_request`. Fixed in 1.95.0.

Both are in the LiteLLM **proxy server**, which mcp-scanner doesn't start. The risk for scanner users is low, but every
SCA tool flags it and it blocks a clean dependency gate.

## Suggested fix

Release 4.8.8 with the relaxed pin and a floor of at least `litellm>=1.100.4`. The open PRs go to 1.106.5 / 1.109.1;
either works. Or merge #285 / #288 so non-LLM analyzers install without litellm.

## Workaround we used

Time-boxed OSV exceptions (`ignoreUntil = 2026-12-15`) in `.github/osv-scanner.toml`, scoped to the CI tool lock file.
Renovate will drop them once a release allows a newer litellm.
