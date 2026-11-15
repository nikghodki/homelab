# OSS Fleet gateway blocks every escalated tool hash and has no way to allow one

Target: github.com/cisco-ai-defense/defenseclaw

## Upstream check (2026-11-15)

- Issues and PRs searched: `fleet verdict allow`, `default-deny fleet`, `threat-intel`. Nothing reports or changes it.
  Open PR #1343 changes how the device holds and revokes escalations, but not the gateway's verdict.
- `edge-connector/README.md` documents the behaviour: "The gateway blocks unknown tool hashes by default; it does not
  run a remote model over the request content." So this is a **feature request**, not a bug.
- Still the same on `main` (`internal/gateway/sidecar.go`, now about line 9336). Status: **not reported.**

## Version

DefenseClaw 1.0.9: OSS gateway with `fleet.enabled`, Edge Connector 1.0.9 daemon (production build, strict mode).

## Environment

- Fleet gateway on Ubuntu arm64 (DGX Spark), per-user install, Mosquitto broker with per-device ACLs
- One Raspberry Pi 4 device, tenant 1 / fleet 1 / device 1, registered over the Fleet API, signed heartbeats and
  signed policy working

## Steps to reproduce

1. Run a production Edge Connector (`DCLAW_DEV_MODE=OFF`) against an OSS Fleet gateway with no cloud inspection
   configured.
2. Make a tool call the device policy marks for escalation (for example an `exec`-class call).
3. Look at the verdict.

## Expected

An operator can decide escalated calls without the cloud product. That could be an API or policy that allows a reviewed
tool hash, or a verdict source the gateway is configured with (policy file, local guardrail or LLM judge, or a human
approval queue).

## Actual

- The device escalates, and the gateway answers BLOCK (severity 3) for every hash it hasn't seen.
- Nothing can change that answer. `POST /api/v1/fleet/threat-intel/push` only takes `revoke_allow_hashes` and
  `emergency`, and no endpoint adds an allow.
- Production devices default to `g_strict_mode = true`, so any call the device can't decide locally is blocked
  synchronously. With `DCLAW_STRICT_MODE=0` it is allowed speculatively and then revoked by the gateway's BLOCK, which
  ends the same way.

## Evidence

- `internal/gateway/sidecar.go:9316-9320` (1.0.9): the verdict cache's miss function is hard-coded:

  ```go
  fleetCache := fleetverdict.NewCache(..., func(tenantID, fleetID uint16, h [32]byte) (fleetverdict.Action, uint8) {
      // Default-deny: unknown tool hashes must not be auto-allowed
      // when no cloud inspection pipeline is configured.
      return fleetverdict.ActionBlock, 3 // severity=3 (high)
  })
  ```

- `internal/fleet/api.go:393-405` lists the Fleet routes. `api.go:986` shows the threat-intel request body has only
  `revoke_allow_hashes` and `emergency`.
- `edge-connector/src/dclaw_core.c:163-170`: production builds start in strict mode unless `DCLAW_STRICT_MODE=0`.

## Suggested fix

Either of these (or both):

1. **An allow-list API:** `POST /api/v1/fleet/verdicts` with `{tenant_id, fleet_id, tool_hash, action, ttl}`. It
   would be authenticated like `policy/push`, audited, stored in the device store, sent to devices the same way
   threat-intel is, and removable with the existing revoke path.
2. **A configurable verdict pipeline:** let `fleet.*` config choose what the cache-miss function calls. Options could
   be a signed policy rule set keyed by hash or tool name and capability, the gateway's own guardrail or LLM judge, or
   the HITL approval queue. Keep BLOCK as the default when nothing is configured.

## Workaround we used

The device's agent (picoclaw) keeps its in-process FFI hook with local decisions only. The daemon and Fleet are used
for registration, signed heartbeats, signed policy, emergency commands and audit, but not for verdicts.
