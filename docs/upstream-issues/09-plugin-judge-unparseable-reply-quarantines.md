# Plugin watcher quarantines an admitted plugin when the LLM judge's reply isn't a bare JSON array

Target: github.com/cisco-ai-defense/defenseclaw

## Upstream check (2026-11-17)

- Searched issues and PRs: `unexpected response shape`, `LLM-SCAN-ERROR`, `expected array of findings`,
  `judge did not run`, `plugin watcher quarantine rescan`.
- Related, but a different cause: #1428 (open; the watcher quarantines Claude Code's update staging clone) and our
  draft [07](07-skill-scanner-path-fail-closed-quarantine.md) (scanner missing from `PATH`).
- Failing closed when the judge really can't run is deliberate (F-0363, "Avarice F-3187"). This issue asks for a
  retry, and for the parser to accept the shapes models actually send. It does not ask for fail open.
- Status: **not reported.**

## Version

DefenseClaw 1.0.9 (per-user installs, Hermes connector, action mode, fail closed). The plugin LLM judge is an
OpenAI-compatible model (qwen3.8-27b behind LiteLLM, thinking off, temperature 0).

## Steps to reproduce

1. Configure the plugin scanner with an LLM (`llm.model`, `scanners.plugin`), and let the watcher admit a plugin.
2. Restart the gateway, or change scanner settings, so the watcher scans every plugin again.
3. In some scans, the model answers with a single finding object (`{"rule_id": …, "severity": …}`) instead of
   `[{…}]`. It may also answer with `{"findings": []}`, or with a sentence before the array.

## Expected

- A reply the parser can't read is treated as a transient judge failure: retry the call a few times (like the 429
  path), and keep the previous verdict for an already-admitted plugin while it's retried.
- The obviously equivalent shapes are accepted: one finding object as one finding, `{"findings": [...]}` as its
  array, and a fenced array after a line of prose. Prose followed by `[]` should still fail. It can contradict itself,
  as in one real reply: "let me flag the subprocess call … []".

## Actual

- `LLM-SCAN-ERROR` "LLM analysis returned an unexpected response shape". The watcher reports "scanner failure
  (fail-closed): the LLM judge did not run, so the scan is incomplete: judge openai/qwen3.8-27b: The LLM analyzer was
  enabled but returned JSON that was not the expected array of findings" and quarantines the plugin. It does this
  even when the same plugin scanned clean minutes before.
- For Hermes this breaks the agent. For example, `plugins/browser/browser_use` is imported for every chat, so after
  the next restart the API answers `500 No module named 'plugins.browser.browser_use'`. `plugins/web/firecrawl` going
  missing breaks `tools.web_tools`.
- Measured on 758 plugin judge calls over 20 hours: 62 (8.2%) failed this way. Of those, 49 were a single finding
  object, 1 was `{"findings": []}`, 6 were prose with or without an array, and 6 were broken or truncated JSON.

## Evidence (1.0.9, installed package)

- `defenseclaw/scanner/plugin_scanner/llm_analyzer.py:242-283` (`_parse_llm_findings`): only one leading fence is
  stripped (`:248`). Anything that isn't a `list` becomes `LLM-SCAN-ERROR` (`:267-271`). There is no retry.
- `defenseclaw/scanner/plugin_scanner/llm_client.py:144`: the bridge subprocess has a fixed `timeout=120` that the
  configured `scanners.plugin_llm.timeout` doesn't change. A model that takes longer (cold start, thinking) also fails
  closed.
- Watcher: any scan error goes to `enforceBlockWith(..., true, reason)` (`internal/watcher/watcher.go`, the same
  path as in [07](07-skill-scanner-path-fail-closed-quarantine.md)). That moves the files even when the plugin was
  already admitted with the same content hash.

## Related: the judge can be given no code at all

`_build_user_prompt` (`llm_analyzer.py:98-110`) stops adding files at the first one that would exceed the
50,000-byte budget, instead of skipping it. When the first file is large, the judge gets only
`## Plugin: <name>\n\n## Source files\n`, without the "(No source files collected …)" note. Hermes' Slack platform
plugin is like this: its `adapter.py` is 372 KB. The judge then answers `[]`, or hallucinates findings: it once
rated Slack CRITICAL, citing `src/index.ts` and `package.json`, files the plugin doesn't have. Suggested fix: skip
files that don't fit, keep going, and add the existing `SCAN-LLM-NO-SOURCE` finding (or a coverage note) when a file
was skipped.

## Suggested fix

1. In `_parse_llm_findings`, accept a single finding object and a `{"findings": [...]}` wrapper. Strip a fence
   anywhere, and leading prose before a non-empty array. Leave everything else as `LLM-SCAN-ERROR`.
2. Retry the LLM call (2–3 times) when the reply can't be parsed, before emitting `LLM-SCAN-ERROR`.
3. In the watcher, when a rescan of an already-admitted plugin (same content hash) fails only because of
   `LLM-SCAN-ERROR`, keep the plugin in place with a warning and retry later, instead of quarantining it. A new or
   changed plugin should still fail closed.
4. Use `scanners.plugin_llm.timeout` for the bridge subprocess instead of the fixed 120 s.

## Our workaround

LiteLLM's post-call hook repairs these replies, but only for the judge keys and the plugin analyzer's prompt. It
never invents findings, and leaves doubtful replies unchanged so they still fail closed
([runbooks/litellm.md](../../runbooks/litellm.md#defenseclaw-judge-replies)). On those 758 calls, DefenseClaw then
reads 98.4% of replies, up from 91.8%. Quarantined plugins are rescanned with the LLM and restored by hand after a
restart ([runbooks/hermes-profiles.md](../../runbooks/hermes-profiles.md)).
