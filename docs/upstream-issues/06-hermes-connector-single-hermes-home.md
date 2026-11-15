# Hermes connector supports one HERMES_HOME per account; a second Hermes profile stops the gateway from starting

Target: github.com/cisco-ai-defense/defenseclaw

## Upstream check (2026-11-15)

- Issues and PRs searched: `HERMES_HOME`, `hermes profile`, `hermes multiple`. The `HERMES_HOME` hits are about
  Windows support and the 1.0.8 release notes. None is about several profiles in one account. Status: **not
  reported.**

## Version

DefenseClaw 1.0.9 per-user install, Hermes connector, action mode, fail closed.

## Environment

Jetson Orin (JetPack 7, Ubuntu arm64). Hermes Agent with two profiles: the default `~/.hermes` and a second profile with
its own `HERMES_HOME` and its own systemd user unit.

## Steps to reproduce

1. As one Linux user, run the Hermes gateway for the default profile with DefenseClaw's Hermes connector installed.
2. Add a second Hermes profile under the same account, with a second `HERMES_HOME` set in its unit's environment, and
   start it.
3. Restart `defenseclaw-gateway`.

## Expected

The connector hooks each Hermes home in the account, or it lets you list several homes. At least, the gateway starts
and reports which home isn't covered.

## Actual

The DefenseClaw gateway refuses to start. Its account evidence for Hermes finds a `HERMES_HOME` that doesn't match the
home it hooked.

**TODO before posting:** paste the exact gateway error line from `~/.defenseclaw/gateway.log` from the time of the
failure (we didn't keep it). The likely source is `internal/hermespath/account_evidence.go:54-57`
(`HERMES_HOME unproven: %s names the Hermes home %s, not %s`).

## Evidence

- The connector resolves a single Hermes home per account: `internal/hermespath/account.go:39-46` and `:135-139`
  (`resolve the Hermes home of ...`, `HERMES_HOME ... of the account's environment ...`).
- The account-environment evidence checks every place that sets `HERMES_HOME` against that one home:
  `account_other.go:67-74` and `:178-198`, `account_evidence.go:42-57`.

## Suggested fix

- Support a list of Hermes homes per account. For example, `connectors.hermes.homes: [...]` installs the hook in each
  and proves each one. Or discover Hermes profiles (`~/.hermes/profiles/*` or each unit's `HERMES_HOME`).
- If only one is supported, keep the gateway running: report the uncovered home as a coverage gap (alert and `doctor`
  finding) and block it, rather than failing the whole gateway start.

## Workaround we used

One Linux user per Hermes profile (`hermes-nikhil` with linger on). Each user has its own per-user DefenseClaw 1.0.9 on
its own port, the same policy and the same telemetry target.
