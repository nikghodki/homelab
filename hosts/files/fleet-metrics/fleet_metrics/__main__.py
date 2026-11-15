import os
from fleet_metrics.server import serve

if __name__ == "__main__":
    port = int(os.environ.get("FLEET_METRICS_PORT", "9109"))
    units = [u.strip() for u in os.environ.get("FLEET_UNITS", "").split(",") if u.strip()]
    serve(port, units)
