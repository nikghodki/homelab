"""Guard the rules the fleet relies on, so an edit cannot loosen them by accident."""

from pathlib import Path

import pytest
import yaml

POLICY = yaml.safe_load((Path(__file__).parents[1] / "homelab.yaml").read_text())


def test_name_matches_file():
    assert POLICY["name"] == "homelab"


@pytest.mark.parametrize("severity", ["critical", "high"])
def test_skills_block_on_install(severity):
    assert POLICY["skill_actions"][severity]["install"] == "block"


@pytest.mark.parametrize("severity", ["CRITICAL", "HIGH"])
def test_mcp_blocks(severity):
    rule = POLICY["scanner_overrides"]["mcp"][severity]
    assert rule["install"] == "block"
    assert rule["runtime"] == "block"


def test_scanner_override_keys_are_uppercase():
    # `defenseclaw policy edit scanner -p` writes lowercase keys next to the preset's
    # uppercase ones; a duplicate makes the effective rule ambiguous.
    for asset, rules in POLICY["scanner_overrides"].items():
        for key in rules:
            assert key == key.upper(), f"{asset}.{key}"


def test_guardrail_and_audit():
    assert POLICY["admission"]["scan_on_install"] is True
    assert POLICY["guardrail"]["block_threshold"] <= 4
    assert POLICY["guardrail"]["hilt"]["enabled"] is True
    assert POLICY["audit"]["log_all_actions"] is True
    assert POLICY["audit"]["retention_days"] >= 90
