"""Robot safety governor for the Pi (plan P5.2). See runbooks/robot-safety.md.

`core` and `sinks` are plain Python (no ROS, no NATS) so they can be tested anywhere;
`node` is the ROS 2 node that wires them to rclpy and NATS on the Pi.
"""
