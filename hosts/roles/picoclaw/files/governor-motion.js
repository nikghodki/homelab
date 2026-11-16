/*
 * Managed by homelab Ansible (role picoclaw); source hosts/roles/picoclaw/files/governor-motion.js.
 * Client for the local motion bridge (robots/safety/motion_bridge, runbooks/robot-safety.md).
 * picoclaw's motion tools go through the safety governor: this sends one JSON request per
 * connection over a Unix socket; the bridge publishes /cmd_vel_in + /safety/heartbeat for the
 * move's duration and answers with what the governor did. Nothing here talks to the car.
 */
import net from "node:net";

export const MOTION_SOCKET = process.env.PICOCLAW_MOTION_SOCKET || "/run/robot-motion/motion.sock";

export function makeMotionClient(socketPath = MOTION_SOCKET) {
  function request(body, timeoutMs) {
    return new Promise((resolve, reject) => {
      const sock = net.createConnection(socketPath);
      let buf = "";
      let done = false;
      const finish = (error, value) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        sock.destroy();
        if (error) reject(error);
        else resolve(value);
      };
      const timer = setTimeout(
        () => finish(new Error(`motion bridge did not answer within ${timeoutMs} ms`)), timeoutMs);
      sock.setEncoding("utf8");
      sock.on("connect", () => sock.write(JSON.stringify(body) + "\n"));
      sock.on("data", (chunk) => {
        buf += chunk;
        const nl = buf.indexOf("\n");
        if (nl < 0) return;
        try { finish(null, JSON.parse(buf.slice(0, nl))); }
        catch (e) { finish(new Error(`motion bridge sent invalid JSON: ${e.message}`)); }
      });
      sock.on("error", (e) => finish(new Error(`motion bridge unreachable at ${socketPath}: ${e.message}`)));
      sock.on("end", () => finish(new Error("motion bridge closed the connection without an answer")));
    });
  }

  const moveTimeout = (ms) => (ms ?? 10000) + 3000;
  return {
    drive: ({ direction, speed, duration_ms }) =>
      request({ op: "drive", direction, speed, duration_ms }, moveTimeout(duration_ms)),
    turn: ({ direction, degrees }) => request({ op: "turn", direction, degrees }, 15000),
    halt: () => request({ op: "halt" }, 15000),
    stop: () => request({ op: "stop" }, 15000),
    status: () => request({ op: "status" }, 3000),
  };
}

// A move the governor refused because the robot must not move at all (not just "something in the way").
export const HARD_STOPS = new Set(["estop", "governor_unavailable", "heartbeat_timeout", "scan_stale",
  "scan_invalid", "above_ceiling", "invalid_command"]);

export function hardStop(result) {
  return Boolean(result && result.blocked && HARD_STOPS.has(result.blocked_reason));
}
