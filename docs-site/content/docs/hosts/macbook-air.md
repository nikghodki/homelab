---
title: MacBook Air (out of scope)
description: The MacBook Air is not part of the managed fleet.
---

The MacBook Air is **out of scope** (design D18, "leave it alone"). It keeps its own OpenClaw, Ollama and Supabase.
It is not in the Ansible inventory, not in k3s, and not covered by DefenseClaw (DefenseClaw was removed from it on
29 September; risk R7, accepted for now).

What the fleet does with it:

- It is on the tailnet as an admin-owned device, so the Tailscale policy lets it reach everything, like other
  `group:admins` devices. The alerting runbook suggests it as an admin device for testing the Dell's Tailscale HTTPS URL.
- Nothing in this repo deploys to it, and nothing here should.

**Coding tools.** Claude Code (terminal and the extension in Cursor) uses the home models through LiteLLM, set up
by the user with `tools/dev-setup/install-mac.sh` ([Use the home models in Claude Code, Cursor and Codex](../agents/coding-tools.md)):
key `claude-code` in the login Keychain, a user LaunchAgent that keeps the `/model` list in sync. The user runs it;
the fleet still deploys nothing here.

If it ever joins the fleet, it needs: an inventory entry, a Tailscale tag, a DefenseClaw install (OpenClaw connector)
and a decision record replacing D18.
