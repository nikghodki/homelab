# `defenseclaw policy edit scanner -p <name>` writes lowercase severity keys next to the preset's uppercase keys

Target: github.com/cisco-ai-defense/defenseclaw

## Upstream check (2026-11-15)

- Issues and PRs searched: `scanner_overrides lowercase`, `policy edit scanner`. Nothing reports it.
- `main` still has `SEVERITIES = ["critical", ...]` and `scanner_ovr.setdefault(severity, ...)`. Status: **not
  reported.**

## Version

DefenseClaw 1.0.9 CLI (per-user install, Linux).

## Steps to reproduce

```bash
defenseclaw policy create homelab --from-preset default
defenseclaw policy edit scanner --type mcp -s high --install block --runtime disable -p homelab
# then open the homelab policy YAML and look at scanner_overrides.mcp
```

## Expected

The existing `scanner_overrides.mcp.HIGH` entry is updated in place, since the presets use uppercase keys.

## Actual

A second entry, `scanner_overrides.mcp.high`, is added next to `HIGH`:

```yaml
scanner_overrides:
  mcp:
    HIGH:    {runtime: allow, file: none, install: none}     # from the preset
    high:    {runtime: disable, file: none, install: block}  # from the edit
```

The OPA compile step upper-cases keys, so both entries become `HIGH` and the one that comes later in the dict wins. The
effective rule depends on key order, and `policy show` lists both.

## Evidence

- `cli/defenseclaw/commands/cmd_policy.py:38`: `SEVERITIES = ["critical", "high", "medium", "low", "info"]` is used as
  the `click.Choice` for `-s`.
- `cmd_policy.py:1624`: `scanner_ovr.setdefault(severity, ...)` uses the lowercase value as the key. `--remove`
  (`:1612`) has the same mismatch, so it can't remove the preset's `HIGH`.
- `cmd_policy.py:2056`: the compile step does `opa_scanner[sev.upper()] = ...`, which collapses the two.
- `policies/default.yaml:41-44` and `strict.yaml:32` use `HIGH` / `CRITICAL`. `policy_catalog.py:50` defines uppercase
  `SEVERITIES` too.
- Side note: the new entry's default `runtime: "allow"` (`:1624`) isn't one of `RUNTIME_CHOICES`
  (`disable`/`enable`).

## Suggested fix

Normalise to one case when reading and when writing: map `-s high` to `HIGH` for `scanner_overrides`, merge an existing
key whatever its case, and have `policy validate` flag case-duplicates. Also add a test that edits a preset-derived
policy and checks there's one key per severity.

## Workaround we used

We edit the policy YAML by hand. Our CI test (`policies/defenseclaw/tests/test_homelab_policy.py`) fails if any
`scanner_overrides` key isn't uppercase.
