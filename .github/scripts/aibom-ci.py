"""cisco-aibom in CI, where there is no LLM (the API base is a closed port, so the BOM is deterministic-only).

The agentic stage then fails fast, but cisco-aibom 1.10.1 sleeps a fixed 30 s (agent._RETRY_COOLDOWN_S) before each
of its two retry passes: 60 of the job's ~110 s. With no LLM a retry cannot succeed, so CI sets it to 0; the report is
identical. Arguments are cisco-aibom's. If an upgrade drops the constant, this warns and runs unchanged.
"""

import sys

import aibom.agentic.agent as agent
from aibom.cli import cli_entry_point

if hasattr(agent, "_RETRY_COOLDOWN_S"):
    agent._RETRY_COOLDOWN_S = 0
else:
    print("::warning::cisco-aibom has no agent._RETRY_COOLDOWN_S any more; .github/scripts/aibom-ci.py does nothing")

sys.argv[0] = "cisco-aibom"
sys.exit(cli_entry_point())
