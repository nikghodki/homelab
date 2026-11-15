# robots

```
robots/
  models/     # robot description (one source → URDF, MJCF, USD)
  tasks/      # training tasks: reward, termination, domain randomization
  policies/   # trained policy manifests (MLflow version, checksum, limits)
  maps/       # SLAM maps
  safety/     # safety-governor limits (speed caps, heartbeat timeout)
```

Changes reach the Pi only while the robot is docked.
