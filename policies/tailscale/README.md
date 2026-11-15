# Tailscale policy

`policy.hujson` is the tailnet's access policy (architecture §4.2). It's applied in the Tailscale admin console;
Tailscale runs the `tests` block and refuses a policy that breaks them.

Order:
1. Tag the fleet devices (list at the top of the file). Tagged devices stop belonging to a person; their keys no
   longer expire.
2. Paste the policy, check the tests pass, save.
3. Check from a family device that Home Assistant and Open WebUI still open.

Later (plan): apply from CI with Tailscale's GitOps action and an API key in GitHub secrets.
