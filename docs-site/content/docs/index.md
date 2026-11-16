---
title: Homelab fleet documentation
description: What the home AI fleet is, where everything runs, how to change it, and what breaks when a piece is down.
---

This site documents the home AI fleet run by nikghodki: two DGX Sparks, a Jetson Orin, a Raspberry Pi 4 and an old
Dell laptop running Omarchy. It is written so that someone new can answer three questions without asking anyone:

1. Where does X run?
2. How do I change it?
3. What breaks if it is down?

The source of truth is the repo `github.com/nikghodki/homelab` (a clone lives on dgx-1 in `~/homelab`). These pages
explain the repo and the live hosts. When a page and the repo disagree, the repo wins; when the repo and a live host
disagree, the difference is listed in [Docs vs live state](decisions/discrepancies.md).

## Quick answers

| Question | Page |
|---|---|
| Which machines exist, and what do they run? | [Hosts](hosts/index.md) |
| Which hostname goes to which backend? | [Front door routes](network/front-door.md) |
| Which ports are open where? | [Ports](network/ports.md) |
| How do I sign in, and who can? | [Pocket ID and sign-in](security/identity.md) |
| Where are the secrets? | [SOPS and age](security/secrets.md) |
| How do alerts reach the phone? | [Alert delivery](observability/alert-delivery.md) |
| What happens when a host is down? | [Failure scenarios](observability/failure-scenarios.md) |
| How do I deploy a change? | [Deploying](operations/deploy.md) |
| Something is broken. | [Incident playbooks](operations/incidents.md) and [Troubleshooting](operations/troubleshooting.md) |
| Why was it built this way? | [Decisions](decisions/index.md) |
| What is done, and what is still open? | [Status](decisions/status.md) |

## Reading order for a new operator

1. [Overview](overview/index.md) and the [glossary](overview/glossary.md).
2. [Day one](operations/index.md) (access, tools, where things live).
3. [Hosts](hosts/index.md) and [Network](network/index.md).
4. [Security](security/index.md), then the section for whatever you are about to change.

## Ground rules

- Every change goes through a pull request and CI. See [PR and merge rules](development/rules.md).
- Code, scripts and files are written on dgx-1, never on the admin laptop (a work machine).
- Commits use only the `nikghodki` noreply identity, with no trailers.
- No secrets in the repo or in these docs. Pages name the SOPS file and key instead
  (for example `secrets/observe.enc.yaml` → `ntfy_phone_password`).

Facts were checked on 2026-11-15 against the repo at `main` and against the live hosts (read-only). Anything that
could not be checked is marked "(unverified)".
