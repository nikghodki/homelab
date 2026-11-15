# robots

```
robots/
  models/     # robot description (one source → URDF, MJCF, USD)
  tasks/      # training tasks: reward, termination, domain randomization
  policies/   # trained policy manifests (MLflow version, checksum, limits)
  maps/       # SLAM maps
  safety/     # safety governor: limits.yaml (speed caps, watchdogs) and the node (governor/); runbooks/robot-safety.md
  sim/        # simulator images (Isaac Lab, MuJoCo) and measure.sh; run via hosts/stacks/sim
```

Changes reach the Pi only while the robot is docked.
