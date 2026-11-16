#!/usr/bin/env python3
"""Check the vulnerability ignores in .trivyignore.yaml: every entry needs an `expired_at` date and a `statement`
(the reason), may not be ignored for more than MAX_DAYS from today, and must not have expired.

  check-trivy-ignores.py [--no-expiry] [FILE]   (default FILE: .trivyignore.yaml)

The nightly runs it as is, so an expired ignore turns the nightly red (Trivy itself would only stop ignoring it).
pr-checks passes --no-expiry: a PR checks the format and the 30-day limit but isn't blocked by a date passing.
Stdlib only (no PyYAML on the runner): it reads the simple block layout used in the file, one `- id:` per entry.
"""
import datetime
import re
import sys

MAX_DAYS = 31  # "30 days out", plus a day of slack for time zones


def entries(text: str) -> list[dict]:
    """The `vulnerabilities:` entries as {"id", "expired_at", "statement", "line"} dicts."""
    out, cur, inside = [], None, False
    for n, line in enumerate(text.splitlines(), 1):
        if re.match(r"^\S", line):  # a top-level key
            inside = line.startswith("vulnerabilities:")
            continue
        if not inside or not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^\s*-\s+id:\s*(\S+)", line)
        if m:
            cur = {"id": m.group(1), "line": n}
            out.append(cur)
            continue
        m = re.match(r"^\s+(expired_at|statement):\s*(.*)$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2).strip().strip("\"'")
    return out


def problems(text: str, today: datetime.date, check_expiry: bool = True) -> list[str]:
    out = []
    for e in entries(text):
        where = f"line {e['line']} {e['id']}"
        if not e.get("statement"):
            out.append(f"{where}: no statement (say why it is accepted)")
        raw = e.get("expired_at")
        if not raw:
            out.append(f"{where}: no expired_at (every vulnerability ignore expires)")
            continue
        try:
            when = datetime.date.fromisoformat(raw)
        except ValueError:
            out.append(f"{where}: expired_at {raw!r} is not a YYYY-MM-DD date")
            continue
        if check_expiry and when <= today:
            out.append(f"{where}: EXPIRED on {when} - bump the image, or re-check and extend with a new reason")
        elif (when - today).days > MAX_DAYS:
            out.append(f"{where}: expires {when}, more than {MAX_DAYS} days out")
    return out


def main(argv: list[str]) -> int:
    check_expiry = "--no-expiry" not in argv
    files = [a for a in argv if not a.startswith("--")] or [".trivyignore.yaml"]
    text = open(files[0], encoding="utf-8").read()
    found = problems(text, datetime.datetime.now(datetime.timezone.utc).date(), check_expiry)
    for p in found:
        print(f"{files[0]}: {p}")
    n = len(entries(text))
    print(f"{files[0]}: {n} vulnerability ignores, {len(found)} problems")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
