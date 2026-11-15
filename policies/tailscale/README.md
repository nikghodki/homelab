# Tailscale policy

`policy.hujson` is the tailnet's access policy (architecture §4.2). It's applied in the Tailscale admin console;
Tailscale runs the `tests` block and refuses a policy that breaks them.

Order (a tag can only be applied once the live policy defines its `tagOwners`):
1. In Access controls, add only the `tagOwners` block from this file to the current policy and save.
   Nothing else changes, so access stays as it is.
2. Tag the fleet devices (list at the top of `policy.hujson`). Tagged devices stop belonging to a person,
   and their keys no longer expire.
3. Replace the whole policy with this file, check that the tests pass, and save.
4. From a family device, check that Home Assistant and Open WebUI still open.

Later (plan): apply from CI with Tailscale's GitOps action and an API key in GitHub secrets.
