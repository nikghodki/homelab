import datetime
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("ign", Path(__file__).parents[1] / "check-trivy-ignores.py")
ign = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ign)

TODAY = datetime.date(2026, 11, 15)
FILE = """\
misconfigurations:
  - id: KSV-0009
    statement: not a vulnerability; never expires
vulnerabilities:
  - id: CVE-1
    purls: [pkg:golang/stdlib@v1.24.3]
    expired_at: {when}
    statement: >-
      a reason
"""


def test_repo_file_is_valid_today():
    text = (Path(__file__).parents[3] / ".trivyignore.yaml").read_text()
    assert ign.problems(text, datetime.datetime.now(datetime.timezone.utc).date()) == []


def test_only_vulnerabilities_are_checked_and_a_future_date_passes():
    assert [e["id"] for e in ign.entries(FILE.format(when="2026-12-15"))] == ["CVE-1"]
    assert ign.problems(FILE.format(when="2026-12-15"), TODAY) == []


def test_expired_fails_unless_no_expiry():
    text = FILE.format(when="2026-11-15")
    assert "EXPIRED" in ign.problems(text, TODAY)[0]
    assert ign.problems(text, TODAY, check_expiry=False) == []


def test_too_far_out_missing_date_or_reason():
    assert "more than" in ign.problems(FILE.format(when="2027-06-01"), TODAY)[0]
    assert "no expired_at" in ign.problems(FILE.replace("    expired_at: {when}\n", ""), TODAY)[0]
    no_reason = "vulnerabilities:\n  - id: CVE-2\n    expired_at: 2026-12-01\n"
    assert "no statement" in ign.problems(no_reason, TODAY)[0]
    assert "not a YYYY-MM-DD" in ign.problems(FILE.format(when="soon"), TODAY)[0]
