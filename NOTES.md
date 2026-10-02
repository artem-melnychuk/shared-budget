# Notes

Decisions made while working, newest first.

## 2026-10-02: sandbox for autonomous work

Same scheme as `nice_events_sandbox`: the agent runs in Docker on a separate clone (branch `agent`), on an internal network whose only way out is a squid allowlist proxy. Differences: the `docker run` flags are written down in `.sandbox/compose.yaml`; `sandbox.ps1` drives it; `.gitattributes` forces LF and the container's git ignores file modes, so a Windows bind mount doesn't show every file as modified; dependencies install from the clone's `requirements.txt` at container start, so a new requirement doesn't need an image rebuild.
