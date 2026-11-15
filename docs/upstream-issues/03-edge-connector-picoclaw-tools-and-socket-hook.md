# Edge Connector: picoclaw's tools are missing from the trusted tool table, and `picoclaw_hook.py` never uses the daemon

Target: github.com/cisco-ai-defense/defenseclaw

## Upstream check (2026-11-15)

- Issues and PRs searched: `picoclaw tool`, `picoclaw hook socket`.
- **The hook part is addressed in open, unmerged PR #1343** (opened 2026-10-19, last updated 2026-10-21, merge state
  dirty). There, `picoclaw_hook.py` goes through `generic_hook.EdgeConnector` over `DCLAW_SOCKET_PATH`, and FFI becomes
  opt-in with `DCLAW_ALLOW_FFI=1`. It isn't in 1.0.9 or on `main`.
- The tool-table part isn't covered. PR #1343 doesn't add these names, and its own "known follow-ups" list a related
  gap: `<name>/response` isn't in the trusted table.
- Status: **hook part in open PR #1343; tool table not reported.** If posted, link #1343 and ask for the table mappings
  as a follow-up.

## Version

DefenseClaw 1.0.9 Edge Connector, with picoclaw on a Raspberry Pi 4 (Debian 13 arm64).

## Steps to reproduce

1. Install `edge-connector/tools/picoclaw_hook.py` as picoclaw's hook, as its docstring says.
2. Have picoclaw call `message` (or `i2c`, `serial`, `spawn`, `cron`, `send_file`, `send_tts`, `subagent`, `spi`).

## Expected

- Each of picoclaw's built-in tools maps to a capability (`SEND_MSG`, `ACTUATE`, `SENSOR_READ`, `EXEC_SHELL`, ...) and
  is judged by policy.
- The shipped picoclaw hook talks to the daemon, so OTA policy, emergency lockdown, revocations and Fleet escalation
  apply to it.

## Actual

- Each of these tools gets `DCLAW_CAP_UNKNOWN` and is refused before cache or cloud lookup (`INVALID_INPUT`). The only
  way to use them is to switch the hook off.
- `picoclaw_hook.py` loads `libdclaw_core` in-process with `ctypes.CDLL` and calls `dclaw_evaluate()` directly. It has
  no socket path at all, so picoclaw's calls never reach the daemon or Fleet, and a policy pushed through Fleet doesn't
  reach the in-process engine.

## Evidence

- `edge-connector/src/decision/policy_table.c:43-291` (`tool_cap_map`) has file, shell, web, messaging
  (`send_message`, `send_email`, `notify`), actuation and sensor names. None of `message`, `i2c`, `serial`, `spawn`,
  `cron`, `send_file`, `send_tts`, `subagent` or `spi` is in it. Lines 296 and 303 return `DCLAW_CAP_UNKNOWN`.
- `edge-connector/tools/picoclaw_hook.py:41` (`import ctypes`), `:194` (`ctypes.CDLL(lib_path)`), and `:249`, `:269`,
  `:295` (`dclaw_evaluate`). The file doesn't mention `socket`.
- `edge-connector/tools/generic_hook.py:440` already has `_SocketBackend` (AF_UNIX, `DCLAW_SOCKET_PATH`, default
  `/run/defenseclaw/defenseclaw.sock`).

## Suggested fix

1. Merge the socket backend for the picoclaw hook (PR #1343's approach: daemon first, fail closed, FFI only by opt-in).
2. Add reviewed mappings for picoclaw's tools to `tool_cap_map`, for example:
   - `message`, `send_file`, `send_tts` → `SEND_MSG`
   - `i2c`, `spi`, `serial` → `ACTUATE` (they can drive hardware; maybe `SENSOR_READ` for read-only ops if the hook
     can tell)
   - `spawn`, `subagent`, `cron` → `EXEC_SHELL` (they start new work outside the current call)
3. Or let a signed OTA policy add tool-name mappings, so new agent tools don't need a firmware rebuild. Keep unknown
   names refused.

## Workaround we used

picoclaw keeps the in-process FFI hook (local decisions only). Tools that aren't in the table can't be used under the
hook. We made a `dclaw-ipc` socket group for a daemon-backed hook once upstream has one.
