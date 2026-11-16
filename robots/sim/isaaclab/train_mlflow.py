"""`isaaclab` CLI with MLflow logging for RSL-RL runs (plan P6.5; runbooks/mlflow.md).

Takes exactly the arguments of the `isaaclab` command (`train --rl_library rsl_rl --task ... physics=...`) and runs
it in-process. If MLFLOW_TRACKING_URI is set and the mlflow client is installed, every RSL-RL OnPolicyRunner gets
MlflowLogWriter as its logger instead of TensorBoard:

- params: the runner config (algorithm, policy, iterations, ...), flattened, plus task, number of envs, physics
  preset and the image's versions; the full runner and env configs as `config/*.json`;
- metrics at every iteration: everything RSL-RL writes (Train/mean_reward, Train/mean_episode_length, Loss/*,
  Policy/mean_std, Perf/total_fps = environment steps/s, Perf/collection_time, Perf/learning_time, Episode/*);
- at the end: final/* (iterations, timesteps, wall time, median and last steps/s, mean reward and episode length),
  the final checkpoint as `checkpoint/model_<it>.pt` and Isaac Lab's dumped `params/*.yaml`.

TensorBoard event files are still written to the run's log dir (MlflowLogWriter is also a SummaryWriter). Isaac Lab
3.0's own `logger` setting only knows tensorboard/wandb/neptune; RSL-RL 5.5 accepts any LogWriter class, so this
script sets `logger` on the runner config. A failed MLflow call prints one line and turns MLflow logging off; it never
stops training. The run ID is printed as `mlflow: run <id> in experiment <id>` (robots/sim/measure.sh reads it).
Experiment: MLFLOW_EXPERIMENT_NAME, default "sim-isaaclab".
"""

from __future__ import annotations

import json
import math
import os
import signal
import statistics
import sys
import time

EXPERIMENT_DEFAULT = "sim-isaaclab"
# Scalars RSL-RL also logs against wall-clock seconds instead of the iteration; MLflow steps are iterations only.
_TIME_AXIS_SUFFIX = "/time"


def _flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, f"{key}."))
        else:
            out[key] = v
    return out


def _arg(argv, name):
    """Value of `--name value` or `--name=value` in argv, or None."""
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


class _State:
    mlflow = None  # the mlflow module while logging is on
    run_id = None
    argv: list[str] = []
    stopped_by_signal = False


def _call(what, fn):
    if _State.mlflow is None:
        return None
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 -- tracking must never break training
        print(f"mlflow: {what} failed ({type(e).__name__}: {e}); not logging any more", flush=True)
        _State.mlflow = None
        return None


def _make_writer_class():
    from rsl_rl.utils.log_writer import LogWriter
    from torch.utils.tensorboard import SummaryWriter

    class MlflowLogWriter(SummaryWriter, LogWriter):
        """RSL-RL LogWriter: TensorBoard files as before, plus the same scalars in one MLflow run."""

        def __init__(self, log_dir: str, **_cfg) -> None:
            super().__init__(log_dir=log_dir, flush_secs=10)
            self.log_dir = log_dir
            self.t0 = time.monotonic()
            self.pending: dict[str, float] = {}
            self.pending_step = None
            self.last: dict[str, float] = {}
            self.fps: list[float] = []
            self.last_step = 0
            self.model_path = None
            self.num_envs = None
            self.steps_per_iter = None

            def go():
                m = _State.mlflow
                m.set_experiment(os.environ.get("MLFLOW_EXPERIMENT_NAME", EXPERIMENT_DEFAULT))
                task = _arg(_State.argv, "--task") or "isaaclab"
                iters = _arg(_State.argv, "--max_iterations")
                run = m.start_run(run_name=f"{task}-{iters}it" if iters else task)
                _State.run_id = run.info.run_id
                m.set_tags({"sim.framework": "isaaclab", "sim.library": "rsl_rl", "sim.task": task,
                            "sim.log_dir": log_dir, "sim.argv": " ".join(_State.argv)[:5000]})
                print(f"mlflow: run {run.info.run_id} in experiment {run.info.experiment_id}", flush=True)
            _call("start_run", go)

        # -- LogWriter --
        def add_scalar(self, tag, scalar_value, global_step=None, *args, **kwargs):
            super().add_scalar(tag, scalar_value, global_step, *args, **kwargs)
            if tag.endswith(_TIME_AXIS_SUFFIX) or global_step is None:
                return
            try:
                v = float(scalar_value)
            except (TypeError, ValueError):
                return
            if not math.isfinite(v):
                return
            if self.pending_step is not None and global_step != self.pending_step:
                self._flush()
            self.pending_step = int(global_step)
            self.pending[tag] = v
            self.last[tag] = v
            if tag == "Perf/total_fps":
                self.fps.append(v)
            self.last_step = int(global_step)

        def _flush(self):
            if self.pending and self.pending_step is not None:
                vals, step = dict(self.pending), self.pending_step
                _call("log_metrics", lambda: _State.mlflow.log_metrics(vals, step=step))
            self.pending.clear()

        def store_config(self, env_cfg, train_cfg) -> None:
            env = env_cfg.to_dict() if hasattr(env_cfg, "to_dict") else {}
            self.num_envs = env.get("scene", {}).get("num_envs")
            self.steps_per_iter = train_cfg.get("num_steps_per_env")

            def go():
                m = _State.mlflow
                flat = {k: v for k, v in _flatten(train_cfg).items() if not k.startswith("logger")}
                params = {k: str(v)[:500] for k, v in flat.items()}
                params.update({
                    "task": _arg(_State.argv, "--task"),
                    "num_envs": self.num_envs,
                    "physics": next((a.split("=", 1)[1] for a in _State.argv if a.startswith("physics=")), None),
                    "sim.dt": env.get("sim", {}).get("dt"),
                    "decimation": env.get("decimation"),
                    "episode_length_s": env.get("episode_length_s"),
                    "versions": _versions(),
                })
                m.log_params({k: str(v)[:500] for k, v in params.items()})
                m.log_dict(_jsonable(train_cfg), "config/agent.json")
                m.log_dict(_jsonable(env), "config/env.json")
            _call("log_params", go)

        def save_model(self, model_path: str, it: int) -> None:
            # Called every save_interval and once at the end; only the last one is uploaded (in stop()).
            self.model_path = model_path

        def save_file(self, path: str) -> None:
            _call("log_artifact", lambda: _State.mlflow.log_artifact(path, artifact_path="code"))

        def stop(self) -> None:
            self._flush()
            self.flush()
            wall = time.monotonic() - self.t0
            final = {"final/iterations": self.last_step + 1, "final/wall_s": wall}
            if self.num_envs and self.steps_per_iter:
                final["final/timesteps"] = (self.last_step + 1) * self.num_envs * self.steps_per_iter
            if self.fps:
                final["final/steps_per_s_median"] = statistics.median(self.fps)
                final["final/steps_per_s_last"] = self.fps[-1]
            for k in ("Train/mean_reward", "Train/mean_episode_length"):
                if k in self.last:
                    final["final/" + k.split("/", 1)[1]] = self.last[k]
            _call("log_metrics", lambda: _State.mlflow.log_metrics(final, step=self.last_step))
            _call("log_dict", lambda: _State.mlflow.log_dict(final, "summary.json"))
            if self.model_path and os.path.isfile(self.model_path):
                path = self.model_path
                _call("log_artifact", lambda: _State.mlflow.log_artifact(path, artifact_path="checkpoint"))
            params_dir = os.path.join(self.log_dir, "params")
            if os.path.isdir(params_dir):
                _call("log_artifacts", lambda: _State.mlflow.log_artifacts(params_dir, artifact_path="params"))
            _call("end_run", lambda: _State.mlflow.end_run("FINISHED"))
            print(f"mlflow: run {_State.run_id} finished", flush=True)
            self.close()

    return MlflowLogWriter


def _versions():
    from importlib.metadata import PackageNotFoundError, version
    out = []
    for p in ("isaaclab", "rsl-rl-lib", "torch", "newton", "warp-lang", "mlflow-skinny"):
        try:
            out.append(f"{p}={version(p)}")
        except PackageNotFoundError:
            pass
    return " ".join(out)


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


def _install():
    """Make every RSL-RL OnPolicyRunner log through MlflowLogWriter."""
    from rsl_rl.runners import OnPolicyRunner

    writer = _make_writer_class()
    original = OnPolicyRunner.__init__

    def init(self, env, train_cfg, log_dir=None, device="cpu"):
        train_cfg = dict(train_cfg)
        train_cfg["logger"] = {"class_name": writer}
        original(self, env, train_cfg, log_dir=log_dir, device=device)

    OnPolicyRunner.__init__ = init


def _on_sigterm(signum, _frame):
    # docker stop (and measure.sh's watchdog) sends SIGTERM to PID 1, which has no default handler in a container.
    _State.stopped_by_signal = True
    raise KeyboardInterrupt(f"signal {signum}")


def main() -> int:
    _State.argv = sys.argv[1:]
    signal.signal(signal.SIGTERM, _on_sigterm)
    if os.environ.get("MLFLOW_TRACKING_URI"):
        try:
            import mlflow
            _State.mlflow = mlflow
            _install()
        except ImportError as e:
            print(f"MLFLOW_TRACKING_URI is set but {e.name} isn't importable; not logging", flush=True)
            _State.mlflow = None

    from isaaclab.cli import cli

    sys.argv = ["isaaclab", *_State.argv]
    status = "FAILED"
    try:
        rc = cli()
        status = "FINISHED" if rc in (None, 0) else "FAILED"
        return rc or 0
    except SystemExit as e:
        status = "FINISHED" if e.code in (None, 0) else "FAILED"
        raise
    finally:
        if _State.stopped_by_signal:
            status = "KILLED"
        # stop() ends a completed run; this ends one that crashed or was stopped (the run would stay RUNNING).
        m = _State.mlflow
        if m is not None and m.active_run() is not None:
            _call("end_run", lambda: m.end_run(status))
            print(f"mlflow: run {_State.run_id} ended {status}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
