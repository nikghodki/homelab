"""Short Brax PPO run on a MuJoCo Playground environment (MJX on the GPU), for smoke tests.

Uses Playground's own PPO hyperparameters for the environment and only shortens the run.
Prints environment steps/s at every evaluation and at the end.
"""

import argparse
import functools
import json
import time

import jax
from brax.training.agents.ppo import networks as ppo_networks
from brax.training.agents.ppo import train as ppo
from mujoco_playground import registry, wrapper
from mujoco_playground.config import dm_control_suite_params, locomotion_params


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

    t0 = time.monotonic()
    marks = []

    def progress(step, metrics):
        now = time.monotonic() - t0
        marks.append((step, now))
        reward = float(metrics.get("eval/episode_reward", float("nan")))
        print(f"step {step:>11,d}  t {now:7.1f}s  eval reward {reward:8.3f}", flush=True)

    ppo.train(
        environment=env,
        eval_env=eval_env,
        wrap_env_fn=wrapper.wrap_for_brax_training,
        network_factory=network_factory,
        progress_fn=progress,
        seed=args.seed,
        **train_params,
    )
    total = time.monotonic() - t0
    # The first progress call comes after JIT compilation; steps/s is measured from there.
    (s0, t_first), (s1, t_last) = marks[0], marks[-1]
    sps = (s1 - s0) / (t_last - t_first) if t_last > t_first else float("nan")
    # The first interval also compiles the training step; the last one is the steady rate.
    (sa, ta), (sb, tb) = marks[-2] if len(marks) > 1 else marks[-1], marks[-1]
    steady = (sb - sa) / (tb - ta) if tb > ta else float("nan")
    print(json.dumps({
        "env": args.env,
        "impl": env_cfg.get("impl", "jax"),
        "num_envs": params.num_envs,
        "timesteps": s1,
        "wall_s": round(total, 1),
        "jit_s": round(t_first, 1),
        "steps_per_s": round(sps),
        "steady_steps_per_s": round(steady),
    }), flush=True)


if __name__ == "__main__":
    main()
