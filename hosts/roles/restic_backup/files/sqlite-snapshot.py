#!/usr/bin/env python3
"""Consistent copies of live SQLite databases (online backup API), so restic never stores a half-written file.
Usage: sqlite-snapshot.py <name>=<path> ... (writes /var/backups/homelab/sqlite/<name>.sqlite3)."""
import os, sqlite3, sys
out = "/var/backups/homelab/sqlite"
os.makedirs(out, mode=0o700, exist_ok=True)
for arg in sys.argv[1:]:
    name, path = arg.split("=", 1)
    if not os.path.exists(path):
        print(f"skip {name}: {path} not found"); continue
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(os.path.join(out, f"{name}.sqlite3.tmp"))
    src.backup(dst); dst.close(); src.close()
    os.replace(os.path.join(out, f"{name}.sqlite3.tmp"), os.path.join(out, f"{name}.sqlite3"))
    print(f"snapshot {name}")
