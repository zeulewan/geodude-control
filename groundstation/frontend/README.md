# Groundstation Frontend

This folder serves the browser UI on the groundstation.

Runtime plan:

- main/prod UI runs on port `8080`
- frontend worktrees can run on `8081`, `8082`, etc.
- all frontends should eventually talk to `groundstation/backend` on port `8070`
- frontend worktrees should not own serial hardware or poll GEO-DUDe directly

The old `groundstation/wheel_control.py` path is kept as a compatibility wrapper for systemd during the refactor.
