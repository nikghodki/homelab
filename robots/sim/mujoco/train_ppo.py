"""Short Brax PPO run on a MuJoCo Playground environment (MJX on the GPU), for smoke tests.

Uses Playground's own PPO hyperparameters for the environment and only shortens the run.
Prints environment steps/s at every evaluation and at the end.

If MLFLOW_TRACKING_URI is set (and mlflow is installed), the run is also logged to MLflow: parameters, the eval
metrics and steps/s at every evaluation, the summary, and the final policy parameters as an artifact. Experiment:
MLFLOW_EXPERIMENT_NAME, default "sim-mujoco". A logging failure never stops training. runbooks/mlflow.md.
"""

import argparse
import functools
import json
import math
import os
import tempfile
import time

import jax
from brax.training.agents.ppo import networks as ppo_networks
from brax.training.agents.ppo import train as ppo
from mujoco_playground import registry, wrapper
from mujoco_playground.config import dm_control_suite_params, locomotion_params


class Tracker:
    """Optional MLflow logging. Without MLFLOW_TRACKING_URI, or after the first error, every call is a no-op."""

    def __init__(self):
        self.mlflow = None
        if not os.environ.get("MLFLOW_TRACKING_URI"):
            return
        try:
            import mlflow
        except ImportError:
            print("MLFLOW_TRACKING_URI is set but mlflow isn't installed; not logging", flush=True)
            return
        self.mlflow = mlflow

    def _call(self, what, fn, *a, **kw):
        if self.mlflow is None:
            return None
        try:
            return fn(*a, **kw)
        except Exception as e:  # noqa: BLE001 -- tracking must never break training
            print(f"mlflow: {what} failed ({type(e).__name__}: {e}); not logging any more", flush=True)
            self.mlflow = None
            return None

    def start(self, run_name, params):
        def go():
            self.mlflow.set_experiment(os.environ.get("MLFLOW_EXPERIMENT_NAME", "sim-mujoco"))
            run = self.mlflow.start_run(run_name=run_name)
            self.mlflow.log_params({k: str(v)[:500] for k, v in params.items()})
            print(f"mlflow: run {run.info.run_id} in experiment {run.info.experiment_id}", flush=True)
        self._call("start_run", go)

    def metrics(self, values, step):
        clean = {k: float(v) for k, v in values.items() if _scalar(v)}
        self._call("log_metrics", lambda: self.mlflow.log_metrics(clean, step=step))

    def policy(self, params):
        def go():
            from brax.io import model
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "policy_params.pkl")
                model.save_params(path, params)
                self.mlflow.log_artifact(path, artifact_path="policy")
        self._call("log_artifact", go)

    def summary(self, summary):
        self._call("log_dict", lambda: self.mlflow.log_dict(summary, "summary.json"))

    def end(self, status="FINISHED"):
        self._call("end_run", lambda: self.mlflow.end_run(status=status))


def _scalar(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="Go1JoystickFlatTerrain")
    ap.add_argument("--timesteps", type=int, default=20_000_000)
    ap.add_argument("--num-envs", type=int, default=0, help="0 = Playground default")
    ap.add_argument("--num-evals", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--impl", choices=["jax", "warp"], default=None,
                    help="MJX backend; default is the environment's own (Go1: warp)")
    args = ap.parse_args()

    print("jax", jax.__version__, "devices", jax.devices(), flush=True)
    if args.env in registry.locomotion.ALL_ENVS:
        params = locomotion_params.brax_ppo_config(args.env)
    else:
        params = dm_control_suite_params.brax_ppo_config(args.env)
    params.num_timesteps = args.timesteps
    params.num_evals = args.num_evals
    if args.num_envs:
        params.num_envs = args.num_envs

    env_cfg = registry.get_default_config(args.env)
    if args.impl:
        env_cfg.impl = args.impl
    env = registry.load(args.env, config=env_cfg)
    eval_env = registry.load(args.env, config=env_cfg)

    train_params = dict(params)
    network_factory = ppo_networks.make_ppo_networks
    if "network_factory" in train_params:
        network_factory = functools.partial(
            ppo_networks.make_ppo_networks, **train_params.pop("network_factory")
        )

    tracker = Tracker()
    tracker.start(
        f"{args.env}-{env_cfg.get('impl', 'jax')}-{args.timesteps // 1_000_000}M",
        {"env": args.env, "impl": env_cfg.get("impl", "jax"), "seed": args.seed,
         "jax": jax.__version__, "device": str(jax.devices()[0]),
         **{k: v for k, v in train_params.items()}, "network_factory": params.get("network_factory", {})},
    )

    t0 = time.monotonic()
    marks = []

    def progress(step, metrics):
        now = time.monotonic() - t0
        reward = float(metrics.get("eval/episode_reward", float("nan")))
        print(f"step {step:>11,d}  t {now:7.1f}s  eval reward {reward:8.3f}", flush=True)
        # steps/s over the interval since the previous evaluation (the first one includes JIT)
        extra = {"wall_s": now}
        if marks:
            (ps, pt) = marks[-1]
            if now > pt:
                extra["steps_per_s"] = (step - ps) / (now - pt)
        marks.append((step, now))
        tracker.metrics({**{k: v for k, v in metrics.items() if k.startswith("eval/")}, **extra}, step)

    try:
        _, policy_params, _ = ppo.train(
            environment=env,
            eval_env=eval_env,
            wrap_env_fn=wrapper.wrap_for_brax_training,
            network_factory=network_factory,
            progress_fn=progress,
            seed=args.seed,
            **train_params,
        )
    except BaseException:
        tracker.end("FAILED")
        raise
    total = time.monotonic() - t0
    # The first progress call comes after JIT compilation; steps/s is measured from there.
    (s0, t_first), (s1, t_last) = marks[0], marks[-1]
    sps = (s1 - s0) / (t_last - t_first) if t_last > t_first else float("nan")
    # The first interval also compiles the training step; the last one is the steady rate.
    (sa, ta), (sb, tb) = marks[-2] if len(marks) > 1 else marks[-1], marks[-1]
    steady = (sb - sa) / (tb - ta) if tb > ta else float("nan")
    summary = {
        "env": args.env,
        "impl": env_cfg.get("impl", "jax"),
        "num_envs": params.num_envs,
        "timesteps": s1,
        "wall_s": round(total, 1),
        "jit_s": round(t_first, 1),
        "steps_per_s": round(sps) if math.isfinite(sps) else None,
        "steady_steps_per_s": round(steady) if math.isfinite(steady) else None,
    }
    print(json.dumps(summary), flush=True)
    tracker.metrics({f"final/{k}": v for k, v in summary.items() if k not in ("env", "impl") and v is not None}, s1)
    tracker.summary(summary)
    tracker.policy(policy_params)
    tracker.end()


if __name__ == "__main__":
    main()
