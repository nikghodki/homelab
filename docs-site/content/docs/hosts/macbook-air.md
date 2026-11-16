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

If it ever joins the fleet, it needs: an inventory entry, a Tailscale tag, a DefenseClaw install (OpenClaw connector)
and a decision record replacing D18.
