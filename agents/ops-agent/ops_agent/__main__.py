"""ops-agent <command>: ingest | worker | portal | migrate | replay (the last one only on dgx-1)."""
from __future__ import annotations

import sys


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "migrate":
        from . import db
        db.migrate()
        print("schema current")
    elif cmd == "worker":
        from .worker.main import run
        run()
    elif cmd in ("ingest", "portal"):
        import uvicorn
        target = "ops_agent.ingest.app:app" if cmd == "ingest" else "ops_agent.portal.app:app"
        uvicorn.run(target, host="0.0.0.0", port=8080, proxy_headers=False, server_header=False, access_log=False)
    elif cmd == "replay":
        from .replay.harness import cli
        cli(sys.argv[2:])
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
