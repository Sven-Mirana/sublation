# Dependencies

## Required

- Python 3.10 or later;
- Python standard library only;
- a Unix-like filesystem for file locks and permission checks.

No third-party Python package is required by the included scripts.

## Full One-Shot Orchestration

The bounded worker orchestrator is designed for macOS and requires the system `sandbox-exec` command. If that isolation layer is missing or rejected, orchestration fails closed instead of running workers unsandboxed.

Worker commands are supplied by the user. Any model provider, login, API key, paid service, or network access used by those commands is outside this package and must be configured and authorized separately.

The optional local delivery adapter accepts loopback HTTP endpoints only. The package does not install or start a room service.

## Optional Runtime Integration

PostToolUse telemetry requires a user-managed hook configuration. The package does not edit agent settings or activate the hook.

`publish.sh` optionally uses `git` and the GitHub CLI, but remains a guarded manual release helper. It is not part of normal Skill execution.
