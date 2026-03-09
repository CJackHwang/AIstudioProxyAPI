# Multi-instance manager

External helper for advanced users who want to run multiple isolated Docker containers from a pool of saved auth profiles.

## What it does

The manager launches one container per auth profile from [`auth_profiles/saved/`](../../auth_profiles/saved/). Each container gets:

- its own host API port
- its own host stream port
- its own dedicated startup profile via [`ACTIVE_AUTH_JSON_PATH`](../../launcher/runner.py)
- the same Docker image and shared API key unless overridden

By default, the manager enforces strict profile isolation at startup. A container starts with its matching file from [`auth_profiles/saved/`](../../auth_profiles/saved/) and does not auto-rotate into other profiles unless you explicitly enable that behavior.

This component is intentionally isolated from the main application. It does not modify the core server code, the existing Docker setup, or the standard launch flow.

## Resource warning

> ⚠️ Each instance can consume around 1 GB RAM or more.
> Running many containers at once may cause memory pressure or OOM kills.
> Review available system memory before launching a large profile pool.

The script shows a visible warning and asks for confirmation before startup unless auto-confirm is enabled.

## Requirements

- Docker installed and running
- Bash 3.2+ on macOS or a newer Bash on Linux
- built image available locally
  - default expected name: `ai-studio-proxy:latest`
  - if you built via `cd docker && docker compose build`, Docker Compose may create `docker-ai-studio-proxy:latest`; the launcher now detects this and falls back automatically when the default image is still configured
  - if you use another tag, pass it explicitly with `--image ...` or set `IMAGE_NAME=...`
- prepared auth files in [`auth_profiles/saved/`](../../auth_profiles/saved/)
- optional [`docker/.env`](../../docker/.env) file if you want containers to inherit the usual Docker configuration

## Files

- [`run-multi-instance.sh`](run-multi-instance.sh) — launcher script
- [`README.md`](README.md) — usage guide

## Startup contract

The launcher now follows a strict startup contract:

1. It mounts the shared [`auth_profiles/`](../../auth_profiles/) tree into the container.
2. It sets `ACTIVE_AUTH_JSON_PATH=/app/auth_profiles/saved/<profile>.json` for that specific container.
3. It copies the selected host profile into [`.multi-instance-runtime/active/`](../../.multi-instance-runtime/) and bind-mounts that copy as `/app/auth_profiles/active/<profile>.json` inside the container.
4. It disables `AUTO_AUTH_ROTATION_ON_STARTUP` and `AUTO_ROTATE_AUTH_PROFILE` by default.

This dual-path startup is intentional. Although [`launcher/runner.py::_resolve_auth_file_path()`](../../launcher/runner.py#L270) and [`browser_utils/initialization/core.py::initialize_page_logic()`](../../browser_utils/initialization/core.py#L48) can consume [`ACTIVE_AUTH_JSON_PATH`](../../launcher/runner.py#L413), real Docker headless startup may still traverse logic that expects at least one file under [`auth_profiles/active/`](../../auth_profiles/active/). The runtime copy avoids polluting the shared host [`auth_profiles/active/`](../../auth_profiles/active/) pool while still satisfying that container-local requirement.

If you really want cross-profile rotation inside each container, use [`--enable-auth-rotation`](run-multi-instance.sh).

## Quick start

Build the image first if needed:

```bash
cd docker
docker compose build
```

After a regular Compose build, the local image is often named `docker-ai-studio-proxy:latest`. The manager still starts from its default `ai-studio-proxy:latest`, but now automatically falls back to `docker-ai-studio-proxy:latest` when that Compose image exists and no custom image override was requested.

Then run the manager from the repository root:

```bash
bash scripts/multi-instance-manager/run-multi-instance.sh
```

## Common examples

Use defaults:

```bash
bash scripts/multi-instance-manager/run-multi-instance.sh
```

Use another image and custom container prefix:

```bash
bash scripts/multi-instance-manager/run-multi-instance.sh \
  --image docker-ai-studio-proxy:latest \
  --container-prefix team-a
```

Use an explicit image override via environment variable:

```bash
IMAGE_NAME=docker-ai-studio-proxy:latest \
  bash scripts/multi-instance-manager/run-multi-instance.sh
```

Shift ports upward to avoid collisions:

```bash
bash scripts/multi-instance-manager/run-multi-instance.sh \
  --base-api-port 3048 \
  --base-stream-port 4120
```

Skip confirmation for automation:

```bash
bash scripts/multi-instance-manager/run-multi-instance.sh --auto-confirm
```

Preview actions without launching containers:

```bash
bash scripts/multi-instance-manager/run-multi-instance.sh --dry-run
```

Allow auth rotation inside each launched container:

```bash
bash scripts/multi-instance-manager/run-multi-instance.sh --enable-auth-rotation
```

## Options

| Option | Description | Default |
| --- | --- | --- |
| `--project-root PATH` | Repository root path | auto-detected |
| `--profile-dir PATH` | Directory with saved auth profiles | `auth_profiles/saved` |
| `--docker-env-file PATH` | Path to mounted Docker env file | `docker/.env` |
| `--image NAME` | Docker image name | `ai-studio-proxy:latest` with automatic fallback to `docker-ai-studio-proxy:latest` after a standard `docker compose build` |
| `--container-prefix PREFIX` | Prefix for launched containers | `ai-proxy` |
| `--api-key KEY` | Shared API key for all containers | `sk-dummy` |
| `--log-level LEVEL` | `SERVER_LOG_LEVEL` value | `INFO` |
| `--base-api-port PORT` | Starting host API port | `2048` |
| `--base-stream-port PORT` | Starting host stream port | `3120` |
| `--memory-per-instance-gb N` | Estimated RAM per container | `1` |
| `--auto-confirm` | Skip confirmation prompt | disabled |
| `--dry-run` | Show commands without running Docker | disabled |
| `--no-docker-env` | Do not mount [`docker/.env`](../../docker/.env) | disabled |
| `--enable-auth-rotation` | Re-enable auth rotation inside launched containers | disabled |
| `--help` | Show help | disabled |

## Environment variables

All major parameters can also be set with environment variables before launch:

```bash
export IMAGE_NAME=docker-ai-studio-proxy:latest
export BASE_API_PORT=3048
export BASE_STREAM_PORT=4120
export AUTO_CONFIRM=true
bash scripts/multi-instance-manager/run-multi-instance.sh
```

When `IMAGE_NAME` or `--image` is set explicitly, the launcher treats that as an intentional override and does not silently replace it with the Compose image name.

Supported variables:

- `PROJECT_ROOT`
- `PROFILE_DIR`
- `DOCKER_ENV_FILE`
- `IMAGE_NAME`
- `CONTAINER_PREFIX`
- `API_KEY`
- `SERVER_LOG_LEVEL`
- `BASE_API_PORT`
- `BASE_STREAM_PORT`
- `MEMORY_PER_INSTANCE_GB`
- `AUTO_CONFIRM`
- `DRY_RUN`
- `MOUNT_DOCKER_ENV`
- `DISABLE_AUTH_ROTATION`
- `EXTRA_DOCKER_ARGS`

## How the manager maps profiles

If the saved pool contains:

- `auth_profiles/saved/user-a.json`
- `auth_profiles/saved/user-b.json`

The script will launch containers similar to:

- `ai-proxy-user-a` on API `2048` and stream `3120`
- `ai-proxy-user-b` on API `2049` and stream `3121`

Inside each container, startup resolves through two aligned paths:

- `/app/auth_profiles/saved/user-a.json` and `/app/auth_profiles/active/user-a.json`
- `/app/auth_profiles/saved/user-b.json` and `/app/auth_profiles/active/user-b.json`

The saved-path mapping is still passed through `ACTIVE_AUTH_JSON_PATH`, and the same host file is also mounted into the container-local [`auth_profiles/active/`](../../auth_profiles/active/) directory. This keeps one-container-one-profile isolation while avoiding the Docker headless startup failure that reports no active profile.

## Port collision behavior

The launcher checks host ports twice:

1. before removing a same-named container
2. again after removal and before starting the replacement container

This prevents a false success path where an old container was removed even though the target port actually belonged to another listener.

If a host port is occupied by another process or container, the script stops before launching replacements.

## Safety checks

Before launch the script validates:

- Docker CLI availability
- Docker daemon availability
- Docker image existence
- profile directory existence
- presence of `*.json` profiles
- host port collisions for all planned instances
- optional [`docker/.env`](../../docker/.env) existence when mounting is enabled

## Stop and inspect containers

List launched containers:

```bash
docker ps --filter "name=^ai-proxy-"
```

Stop one container:

```bash
docker rm -f ai-proxy-user-a
```

Stop all containers for the default prefix:

```bash
containers=$(docker ps -aq --filter "name=^ai-proxy-")
[ -n "$containers" ] && docker rm -f $containers
```

Check logs for one instance:

```bash
docker logs -f ai-proxy-user-a
```

## Notes

- The manager is intended for advanced operators.
- It is an external wrapper, not a replacement for the standard single-instance flow.
- For the normal Docker path, continue using [`docker/README.md`](../../docker/README.md) and [`docs/deployment-and-operations.md`](../../docs/deployment-and-operations.md).
