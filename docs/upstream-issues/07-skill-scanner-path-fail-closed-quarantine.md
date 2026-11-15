# Gateway under a systemd user unit can't find `skill-scanner`, quarantines every skill, and `skill restore` then fails

Target: github.com/cisco-ai-defense/defenseclaw

## Upstream check (2026-11-15)

- Issues and PRs searched: `skill-scanner PATH`, `executable file not found`, `scanner failure fail-closed quarantine`,
  `skill restore`.
- Related but different:
  - #796 (closed): a `~/.local/bin/skill-scanner` shim had the wrong shebang.
  - #1428 (open): the plugin watcher quarantines Claude Code's update staging clone.
- Blocking on a scanner error is deliberate (`watcher.go:2793-2800`, "Avarice F-3187"). This issue asks to keep the
  block but not move the files.
- Status: **not reported.**

## Version

DefenseClaw 1.0.9 per-user install (`~/.local/bin/skill-scanner` linked into `~/.defenseclaw/.venv`).

## Environment

Linux, gateway started by a systemd **user** unit. A user unit's `PATH` doesn't include `~/.local/bin` unless you set
it, unlike a login shell.

## Steps to reproduce

1. Start `defenseclaw-gateway` from a systemd user unit without `~/.local/bin` on `PATH`.
2. Let the watcher see a skill (start up, or touch a skill folder).
3. Run `defenseclaw skill list`, then `defenseclaw skill restore <name>` after the agent has created the skill folder
   again.

## Expected

- The gateway finds the scanner it installed, whatever `PATH` it was started with.
- If the scanner can't run, the skill is blocked or disabled, but its files stay where they are. A broken scanner isn't
  evidence that the skill is malicious.
- `skill restore` can get a skill back even when the agent has already made a new folder at the old path.

## Actual

- Every skill is quarantined: `scanner failure (fail-closed): ... exec: "skill-scanner": executable file not found in
  $PATH`.
- The agent (or its updater) makes the skill folder again. Then `skill restore` stops with
  `error: restore destination already exists for '<name>'; provenance was preserved`, and the user has to move folders
  by hand.

## Evidence

- `internal/config/defaults.go:138` and `config.go:3996`: the default `scanners.skill_scanner.binary` is the bare name
  `skill-scanner`.
- `internal/scanner/skill_binary_nonwindows.go:17-30`: `resolveDefaultSkillScanner` uses `exec.LookPath`. If that
  fails, it returns the bare name, so the lookup depends on the caller's `PATH`.
- The installer knows the absolute path: `internal/enterprisehooks/user_binaries_unix.go:40-50` lists `skill-scanner`
  among the launchers it links into `~/.defenseclaw/.venv`.
- `internal/watcher/watcher.go:2793-2820` and `:3406`: on any scan error, `enforceBlockWith(ctx, evt, true, reason)`
  blocks and quarantines.
- `cli/defenseclaw/commands/cmd_skill.py:5437-5442`: restore refuses when the destination exists.

## Suggested fix

1. Resolve scanner binaries from the install, not from `PATH`: `~/.defenseclaw/.venv/bin/skill-scanner` (and
   `mcp-scanner`), or record absolute paths in config at install time. `doctor` should warn when the configured
   scanner can't be executed.
2. On a **scanner failure** (as opposed to a finding), block and disable the skill at runtime, but don't move its files.
   Retry the scan with backoff and raise one alert ("scanner unavailable"), not one per skill.
3. `skill restore`: add `--replace` (move the existing destination aside with its provenance) or `--merge-check`, and
   name it in the error.

## Workaround we used

- Put `~/.local/bin` on the unit's `PATH`, for example
  `Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin`. An absolute `scanners.skill_scanner.binary` in config
  also works.
- Move each re-created skill folder aside by hand, then `skill restore` every quarantined skill.
