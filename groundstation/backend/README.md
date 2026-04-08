# Groundstation Backend

This folder is reserved for the shared groundstation hub service.

Planned runtime:

- runs from the main checkout only
- listens on port `8070`
- polls the GEO-DUDe hardware backend once
- caches telemetry and run logs
- owns the control lock
- serves stable APIs to prod and worktree frontends

Worktree frontends should talk to this hub instead of polling GEO-DUDe directly.
