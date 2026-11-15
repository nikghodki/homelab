#!/usr/bin/env python3
"""Keep the observe stack in step with a DefenseClaw release (plan P1.11).

check: verbatim files match the pinned release, and the upstream sources of
       adapted files still have the recorded sha256.
sync:  copy verbatim files from the pinned release and print the upstream diff
       of every adapted file that changed since `adapted_base`, then record the
       new hashes. Port those diffs by hand before committing.

Usage: defenseclaw-bundle.py check|sync [--manifest PATH]
"""

import argparse
import difflib
import hashlib
import io
import re
import sys
import tarfile
from pathlib import Path

import httpx
import yaml

REPO = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO / "hosts/stacks/observe/defenseclaw-bundle.yaml"
TARBALL = "https://codeload.github.com/cisco-ai-defense/defenseclaw/tar.gz/refs/tags/{version}"


def fetch_bundle(version, root):
    """Return {relative path under root: bytes} for one release."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"not a release version: {version!r}")
    resp = httpx.get(TARBALL.format(version=version), timeout=60)
    resp.raise_for_status()
    data = resp.content
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = member.name.split("/", 1)
            if len(parts) == 2 and parts[1].startswith(root + "/"):
                files[parts[1][len(root) + 1:]] = tar.extractfile(member).read()
    return files


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verbatim_pairs(manifest, upstream):
    """Expand directory entries (ending in /) into file pairs."""
    for src, dest in manifest["verbatim"].items():
        if src.endswith("/"):
            for name in sorted(upstream):
                if name.startswith(src):
                    yield name, str(Path(dest) / name[len(src):])
        else:
            yield src, dest


def check(manifest, upstream):
    problems = []
    for src, dest in verbatim_pairs(manifest, upstream):
        if src not in upstream:
            problems.append(f"{src}: missing upstream")
        elif not (REPO / dest).is_file():
            problems.append(f"{dest}: missing here (new upstream file)")
        elif (REPO / dest).read_bytes() != upstream[src]:
            problems.append(f"{dest}: differs from upstream {src}")
    for dest_dir in {d for s, d in manifest["verbatim"].items() if s.endswith("/")}:
        expected = {d for s, d in verbatim_pairs(manifest, upstream) if d.startswith(dest_dir)}
        for path in sorted((REPO / dest_dir).iterdir()):
            rel = str(path.relative_to(REPO))
            if path.suffix == ".json" and rel not in expected:
                problems.append(f"{rel}: no longer upstream")
    for src, entry in manifest["adapted"].items():
        if src not in upstream:
            problems.append(f"{src}: adapted source missing upstream")
        elif sha256(upstream[src]) != entry["upstream_sha256"]:
            problems.append(f"{entry['dest']}: upstream {src} changed; run sync and port the diff")
    return problems


def sync(manifest, upstream, manifest_path):
    for src, dest in verbatim_pairs(manifest, upstream):
        target = REPO / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(upstream[src])
    base = None
    for src, entry in manifest["adapted"].items():
        new = upstream.get(src)
        if new is None or sha256(new) == entry["upstream_sha256"]:
            continue
        if base is None:
            base = fetch_bundle(manifest["adapted_base"], manifest["root"])
        old = base.get(src, b"").decode().splitlines(keepends=True)
        sys.stdout.writelines(difflib.unified_diff(
            old, new.decode().splitlines(keepends=True),
            f"{manifest['adapted_base']}/{src}", f"{manifest['version']}/{src}"))
        print(f"^^^ port into {entry['dest']}\n")
        entry["upstream_sha256"] = sha256(new)
    text = manifest_path.read_text()
    old_base = f"adapted_base: \"{manifest['adapted_base']}\""
    text = text.replace(old_base, f"adapted_base: \"{manifest['version']}\"")
    for src, entry in manifest["adapted"].items():
        lines = text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.strip() == f"{src}:":
                for j in range(i + 1, min(i + 4, len(lines))):
                    if "upstream_sha256:" in lines[j]:
                        indent = lines[j][: len(lines[j]) - len(lines[j].lstrip())]
                        lines[j] = f"{indent}upstream_sha256: {entry['upstream_sha256']}\n"
        text = "".join(lines)
    manifest_path.write_text(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["check", "sync"])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    manifest = yaml.safe_load(args.manifest.read_text())
    upstream = fetch_bundle(manifest["version"], manifest["root"])
    if args.command == "sync":
        sync(manifest, upstream, args.manifest)
        manifest = yaml.safe_load(args.manifest.read_text())
    problems = check(manifest, upstream)
    for problem in problems:
        print(f"::error::{problem}" if args.command == "check" else problem)
    print(f"DefenseClaw {manifest['version']}: {'OK' if not problems else f'{len(problems)} problem(s)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
