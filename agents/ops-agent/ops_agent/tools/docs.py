"""ops-docs: the repo's runbooks and docs, chunked by heading, searched with Postgres full-text search.

Indexed at a commit; the replay harness indexes the commit that was on main at the incident's time, so the agent
can't read a postmortem written after the fact. Files that hold the evaluation's answers are never indexed.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .. import db

INCLUDE = re.compile(r"^(runbooks/|docs/|docs-site/content/|decisions/|hosts/README|cluster/README|cluster/apps/README|"
                     r"hosts/stacks/[^/]+/README|README\.md)")
EXCLUDE = re.compile(r"^(docs/ambient-agent-design\.md|decisions/0013-|agents/ops-agent/)")
SUFFIX = (".md",)


def chunks(text: str, max_lines: int = 60) -> list[tuple[int, int, str, str]]:
    out, heading, start, buf = [], "", 1, []
    lines = text.splitlines()
    for i, line in enumerate(lines, 1):
        if line.startswith("#") and buf:
            out.append((start, i - 1, heading, "\n".join(buf)))
            buf, start = [], i
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        buf.append(line)
        if len(buf) >= max_lines:
            out.append((start, i, heading, "\n".join(buf)))
            buf, start = [], i + 1
    if buf:
        out.append((start, len(lines), heading, "\n".join(buf)))
    return [c for c in out if c[3].strip()]


def index_commit(repo: str, commit: str) -> int:
    """(Re)index every included file at `commit` (from the git object store, not the work tree)."""
    if db.one("SELECT 1 FROM docs_chunks WHERE commit = %s LIMIT 1", commit):
        return 0
    files = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "--name-only", commit], capture_output=True,
                           text=True, check=True).stdout.splitlines()
    n = 0
    with db.conn() as c:
        for f in files:
            if not f.endswith(SUFFIX) or not INCLUDE.match(f) or EXCLUDE.match(f):
                continue
            text = subprocess.run(["git", "-C", repo, "show", f"{commit}:{f}"], capture_output=True, text=True).stdout
            for a, b, h, body in chunks(text):
                c.execute("INSERT INTO docs_chunks (commit, path, line_from, line_to, heading, body) VALUES (%s,%s,%s,%s,%s,%s)",
                          (commit, f, a, b, h[:200], body[:8000]))
                n += 1
    return n


def latest_commit() -> str | None:
    r = db.one("SELECT commit FROM docs_chunks ORDER BY id DESC LIMIT 1")
    return r["commit"] if r else None


def search(query: str, commit: str | None, limit: int = 5) -> list[dict]:
    commit = commit or latest_commit()
    if not commit:
        return []
    return db.all_(
        "SELECT path, line_from, line_to, heading, body, ts_rank(tsv, q) AS rank FROM docs_chunks, "
        "websearch_to_tsquery('english', %s) q WHERE commit = %s AND tsv @@ q ORDER BY rank DESC LIMIT %s",
        query, commit, limit) or db.all_(
        # fall back to OR of the words when the AND query finds nothing
        "SELECT path, line_from, line_to, heading, body, ts_rank(tsv, q) AS rank FROM docs_chunks, "
        "to_tsquery('english', %s) q WHERE commit = %s AND tsv @@ q ORDER BY rank DESC LIMIT %s",
        " | ".join(re.findall(r"[A-Za-z0-9]{3,}", query)) or "x", commit, limit)


def link(repo_slug: str, commit: str, path: str, a: int, b: int) -> str:
    return f"https://github.com/{repo_slug}/blob/{commit}/{path}#L{a}-L{b}"
