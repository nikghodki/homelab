#!/usr/bin/env python3
"""Ask Me overlay patch for the upstream Open WebUI image (runbooks/open-webui.md, "Ask Me overlay").

Two edits, each must match exactly once, or the build fails with a message saying which one and why:

1. backend/open_webui/env.py: drop the two lines that append " (Open WebUI)" to a custom WEBUI_NAME.
   The licence comment above them stays.
2. build/index.html: the <title> shown before the app has loaded (the app then sets it from WEBUI_NAME).

The branding change relies on the Open WebUI License's clause for deployments with at most 50 end users in any
rolling 30 days (the household qualifies). Copyright notices are not touched.

    patch_branding.py --root /app --title "Ask Me"        # in the Dockerfile
    patch_branding.py --root <dir> --title "Ask Me" --check   # only report whether it would apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ENV_FILE = "backend/open_webui/env.py"
INDEX_FILE = "build/index.html"

SUFFIX_BLOCK = "if WEBUI_NAME != 'Open WebUI':\n    WEBUI_NAME += ' (Open WebUI)'\n"
SUFFIX_REPLACEMENT = (
    "# Ask Me overlay (homelab): no \" (Open WebUI)\" suffix. Allowed by the Open WebUI License for deployments\n"
    "# with at most 50 end users in any rolling 30 days.\n"
)
TITLE_UPSTREAM = "<title>Open WebUI</title>"


class PatchError(Exception):
    """The upstream file no longer looks the way this patch expects."""


def patch_env(text: str) -> str:
    """Remove the " (Open WebUI)" suffix block from env.py."""
    count = text.count(SUFFIX_BLOCK)
    if count != 1:
        if SUFFIX_REPLACEMENT in text:
            raise PatchError(f"{ENV_FILE}: already patched")
        raise PatchError(
            f"{ENV_FILE}: expected the WEBUI_NAME suffix block exactly once, found it {count} times; "
            "upstream changed how the name is built. Read the new env.py and update patch_branding.py"
        )
    if "WEBUI_NAME = os.getenv('WEBUI_NAME', 'Open WebUI')" not in text:
        raise PatchError(f"{ENV_FILE}: WEBUI_NAME is no longer read from the environment as before")
    out = text.replace(SUFFIX_BLOCK, SUFFIX_REPLACEMENT)
    if "(Open WebUI)'" in out:
        raise PatchError(f"{ENV_FILE}: another \" (Open WebUI)\" suffix is still there after patching")
    return out


def patch_index(text: str, title: str) -> str:
    """Set the static page title (shown until the app sets it from WEBUI_NAME)."""
    if not title or "<" in title or ">" in title or "&" in title:
        raise PatchError(f"title {title!r}: must be plain text")
    count = text.count(TITLE_UPSTREAM)
    if count != 1:
        raise PatchError(
            f"{INDEX_FILE}: expected {TITLE_UPSTREAM} exactly once, found it {count} times; "
            "upstream changed the page head. Update patch_branding.py"
        )
    return text.replace(TITLE_UPSTREAM, f"<title>{title}</title>")


def run(root: Path, title: str, check: bool) -> list[str]:
    """Patch (or, with check, only test) the files under root; returns what was done."""
    done = []
    for rel, fn in ((ENV_FILE, patch_env), (INDEX_FILE, lambda t: patch_index(t, title))):
        path = root / rel
        if not path.is_file():
            raise PatchError(f"{rel}: not found under {root}; upstream moved it")
        new = fn(path.read_text(encoding="utf-8"))
        if not check:
            path.write_text(new, encoding="utf-8")
        done.append(f"{rel}: {'would patch' if check else 'patched'}")
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path("/app"))
    ap.add_argument("--title", default="Ask Me")
    ap.add_argument("--check", action="store_true", help="only check that the patch applies")
    args = ap.parse_args(argv)
    try:
        for line in run(args.root, args.title, args.check):
            print(line)
    except PatchError as e:
        print(f"ERROR: the Ask Me patch no longer applies: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
