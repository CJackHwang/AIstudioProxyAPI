#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PROJECT_ROOT="${PROJECT_ROOT:-$DEFAULT_PROJECT_ROOT}"
PROFILE_DIR="${PROFILE_DIR:-$PROJECT_ROOT/auth_profiles/saved}"
DOCKER_ENV_FILE="${DOCKER_ENV_FILE:-$PROJECT_ROOT/docker/.env}"
DEFAULT_IMAGE_NAME="ai-studio-proxy:latest"
COMPOSE_DEFAULT_IMAGE_NAME="docker-ai-studio-proxy:latest"
IMAGE_NAME="${IMAGE_NAME:-$DEFAULT_IMAGE_NAME}"
IMAGE_NAME_SOURCE="default"
CONTAINER_PREFIX="${CONTAINER_PREFIX:-ai-proxy}"
API_KEY="${API_KEY:-sk-dummy}"
SERVER_LOG_LEVEL="${SERVER_LOG_LEVEL:-INFO}"
BASE_API_PORT="${BASE_API_PORT:-2048}"
BASE_STREAM_PORT="${BASE_STREAM_PORT:-3120}"
MEMORY_PER_INSTANCE_GB="${MEMORY_PER_INSTANCE_GB:-1}"
AUTO_CONFIRM="${AUTO_CONFIRM:-false}"
DRY_RUN="${DRY_RUN:-false}"
MOUNT_DOCKER_ENV="${MOUNT_DOCKER_ENV:-true}"
DISABLE_AUTH_ROTATION="${DISABLE_AUTH_ROTATION:-true}"
EXTRA_DOCKER_ARGS="${EXTRA_DOCKER_ARGS:-}"
RUNTIME_STATE_DIR="${RUNTIME_STATE_DIR:-$PROJECT_ROOT/.multi-instance-runtime}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/multi-instance-manager/run-multi-instance.sh [options]

Options:
  --project-root PATH         Path to repository root
  --profile-dir PATH          Directory with saved auth profiles
  --docker-env-file PATH      Path to docker/.env file to mount into containers
  --image NAME                Docker image name to run
  --container-prefix PREFIX   Prefix for container names
  --api-key KEY               Shared API key for launched containers
  --log-level LEVEL           SERVER_LOG_LEVEL value
  --base-api-port PORT        Starting host port for API service
  --base-stream-port PORT     Starting host port for stream service
  --memory-per-instance-gb N  Estimated RAM usage per instance
  --auto-confirm              Skip interactive confirmation
  --dry-run                   Print actions without running docker
  --no-docker-env             Do not mount docker/.env into containers
  --enable-auth-rotation      Allow containers to rotate into other profiles
  --help                      Show this help

Environment variables can also be used:
  PROJECT_ROOT PROFILE_DIR DOCKER_ENV_FILE IMAGE_NAME CONTAINER_PREFIX API_KEY
  SERVER_LOG_LEVEL BASE_API_PORT BASE_STREAM_PORT MEMORY_PER_INSTANCE_GB
  AUTO_CONFIRM DRY_RUN MOUNT_DOCKER_ENV DISABLE_AUTH_ROTATION EXTRA_DOCKER_ARGS
  RUNTIME_STATE_DIR
EOF
}

log() {
  printf '%s\n' "$*"
}

warn() {
  printf '⚠️  %s\n' "$*" >&2
}

die() {
  printf '❌ %s\n' "$*" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

trim() {
  local value="$1"
  value="${value#${value%%[![:space:]]*}}"
  value="${value%${value##*[![:space:]]}}"
  printf '%s' "$value"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project-root)
        PROJECT_ROOT="$2"
        shift 2
        ;;
      --profile-dir)
        PROFILE_DIR="$2"
        shift 2
        ;;
      --docker-env-file)
        DOCKER_ENV_FILE="$2"
        shift 2
        ;;
      --image)
        IMAGE_NAME="$2"
        IMAGE_NAME_SOURCE="cli"
        shift 2
        ;;
      --container-prefix)
        CONTAINER_PREFIX="$2"
        shift 2
        ;;
      --api-key)
        API_KEY="$2"
        shift 2
        ;;
      --log-level)
        SERVER_LOG_LEVEL="$2"
        shift 2
        ;;
      --base-api-port)
        BASE_API_PORT="$2"
        shift 2
        ;;
      --base-stream-port)
        BASE_STREAM_PORT="$2"
        shift 2
        ;;
      --memory-per-instance-gb)
        MEMORY_PER_INSTANCE_GB="$2"
        shift 2
        ;;
      --auto-confirm)
        AUTO_CONFIRM="true"
        shift
        ;;
      --dry-run)
        DRY_RUN="true"
        shift
        ;;
      --no-docker-env)
        MOUNT_DOCKER_ENV="false"
        shift
        ;;
      --enable-auth-rotation)
        DISABLE_AUTH_ROTATION="false"
        shift
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        die "Unknown option: $1"
        ;;
    esac
  done
}

require_integer() {
  local name="$1"
  local value="$2"
  [[ "$value" =~ ^[0-9]+$ ]] || die "$name must be a non-negative integer, got: $value"
}

validate_paths() {
  [[ -d "$PROJECT_ROOT" ]] || die "Project root not found: $PROJECT_ROOT"
  [[ -d "$PROFILE_DIR" ]] || die "Profile directory not found: $PROFILE_DIR"

  if [[ "$MOUNT_DOCKER_ENV" == "true" && ! -f "$DOCKER_ENV_FILE" ]]; then
    die "docker env file not found: $DOCKER_ENV_FILE"
  fi

  mkdir -p "$RUNTIME_STATE_DIR/active"
}

resolve_image_name() {
  if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    return 0
  fi

  if [[ "$IMAGE_NAME_SOURCE" == "default" && "$IMAGE_NAME" == "$DEFAULT_IMAGE_NAME" ]] \
    && docker image inspect "$COMPOSE_DEFAULT_IMAGE_NAME" >/dev/null 2>&1; then
    warn "Docker image $DEFAULT_IMAGE_NAME not found; falling back to Compose-built image $COMPOSE_DEFAULT_IMAGE_NAME"
    IMAGE_NAME="$COMPOSE_DEFAULT_IMAGE_NAME"
    return 0
  fi

  die "docker image not found: $IMAGE_NAME"
}

check_docker() {
  command_exists docker || die "docker command not found"
  docker info >/dev/null 2>&1 || die "docker daemon is not available"
  resolve_image_name
}

discover_profiles() {
  shopt -s nullglob
  PROFILE_FILES=("$PROFILE_DIR"/*.json)
  shopt -u nullglob

  [[ ${#PROFILE_FILES[@]} -gt 0 ]] || die "No .json auth profiles found in $PROFILE_DIR"
}

print_memory_warning() {
  local instance_count="${#PROFILE_FILES[@]}"
  local estimated_total_gb=$((instance_count * MEMORY_PER_INSTANCE_GB))

  log "============================================================"
  warn "Multi-instance mode launches one isolated Docker container per auth profile."
  warn "Each instance may consume about ${MEMORY_PER_INSTANCE_GB} GB RAM or more."
  warn "Planned instances: ${instance_count}"
  warn "Estimated RAM requirement: ~${estimated_total_gb} GB"
  warn "Running too many instances can trigger memory pressure or OOM kills."
  log "============================================================"
}

confirm_launch() {
  [[ "$AUTO_CONFIRM" == "true" ]] && return 0

  local answer
  printf 'Continue launching %s containers? [y/N]: ' "${#PROFILE_FILES[@]}"
  read -r answer
  answer="$(trim "$answer")"
  [[ "$answer" =~ ^([yY][eE][sS]|[yY])$ ]] || die "Launch cancelled by user"
}

port_in_use() {
  local port="$1"

  if command_exists lsof; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi

  docker ps --format '{{.Ports}}' | grep -E "(^|[ ,])0\.0\.0\.0:${port}->|(^|[ ,])127\.0\.0\.1:${port}->|(^|[ ,])\[::\]:${port}->" >/dev/null 2>&1
}

container_exists() {
  local container_name="$1"
  docker ps -a --format '{{.Names}}' | grep -Fx "$container_name" >/dev/null 2>&1
}

container_uses_port() {
  local container_name="$1"
  local port="$2"

  docker ps --filter "name=^${container_name}$" --format '{{.Ports}}' | grep -E "(^|[ ,])127\.0\.0\.1:${port}->|(^|[ ,])0\.0\.0\.0:${port}->|(^|[ ,])\[::\]:${port}->" >/dev/null 2>&1
}

check_port_available() {
  local port="$1"
  local port_role="$2"
  local container_name="$3"

  if port_in_use "$port"; then
    if [[ -n "$container_name" ]] && container_uses_port "$container_name" "$port"; then
      return 0
    fi

    die "Host ${port_role} port already in use by another listener: $port"
  fi
}

sanitize_name() {
  local value="$1"
  value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  value="${value//[^a-z0-9_.-]/-}"
  value="${value#-}"
  value="${value%-}"
  printf '%s' "$value"
}

stop_existing_container() {
  local container_name="$1"

  if container_exists "$container_name"; then
    log "♻️  Removing existing container: $container_name"
    if [[ "$DRY_RUN" != "true" ]]; then
      docker rm -f "$container_name" >/dev/null
    fi
  fi
}

prepare_container_ports() {
  local container_name="$1"
  local api_port="$2"
  local stream_port="$3"

  check_port_available "$api_port" "API" "$container_name"
  check_port_available "$stream_port" "stream" "$container_name"
  stop_existing_container "$container_name"
  check_port_available "$api_port" "API" ""
  check_port_available "$stream_port" "stream" ""
}

launch_container() {
  local profile_path="$1"
  local profile_name="$2"
  local api_port="$3"
  local stream_port="$4"
  local container_name="$5"
  local container_profile_path="/app/auth_profiles/saved/${profile_name}.json"
  local runtime_active_host_path="$RUNTIME_STATE_DIR/active/${container_name}.json"
  local container_active_profile_path="/app/auth_profiles/active/${profile_name}.json"

  cp "$profile_path" "$runtime_active_host_path"

  local -a docker_args=(
    run -d
    --name "$container_name"
    --restart unless-stopped
    -p "127.0.0.1:${api_port}:2048"
    -p "127.0.0.1:${stream_port}:3120"
    -v "$PROJECT_ROOT/auth_profiles:/app/auth_profiles"
    -v "$runtime_active_host_path:${container_active_profile_path}:ro"
    -e "ACTIVE_AUTH_JSON_PATH=${container_profile_path}"
    -e "API_KEY=${API_KEY}"
    -e "SERVER_LOG_LEVEL=${SERVER_LOG_LEVEL}"
  )

  if [[ "$MOUNT_DOCKER_ENV" == "true" ]]; then
    docker_args+=( -v "$DOCKER_ENV_FILE:/app/.env:ro" )
  fi

  if [[ "$DISABLE_AUTH_ROTATION" == "true" ]]; then
    docker_args+=(
      -e "AUTO_AUTH_ROTATION_ON_STARTUP=false"
      -e "AUTO_ROTATE_AUTH_PROFILE=false"
    )
  fi

  if [[ -n "$EXTRA_DOCKER_ARGS" ]]; then
    # shellcheck disable=SC2206
    local -a extra_args=( $EXTRA_DOCKER_ARGS )
    docker_args+=( "${extra_args[@]}" )
  fi

  docker_args+=( "$IMAGE_NAME" )

  log "------------------------------------------------------------"
  log "🚀 Launching profile: $profile_name"
  log "   Container:      $container_name"
  log "   API port:       $api_port"
  log "   Stream:         $stream_port"
  log "   Saved auth:     $container_profile_path"
  log "   Active mount:   $container_active_profile_path"
  log "   Startup mode:   dual-path (ACTIVE_AUTH_JSON_PATH + active-file mount)"
  if [[ "$DISABLE_AUTH_ROTATION" == "true" ]]; then
    log "   Rotation:       disabled for strict profile isolation"
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    printf 'DRY RUN: docker'
    printf ' %q' "${docker_args[@]}"
    printf '\n'
  else
    docker "${docker_args[@]}" >/dev/null
  fi
}

print_summary() {
  log ""
  log "✅ Done. Processed profiles: ${#PROFILE_FILES[@]}"
  log "🔑 Shared API key: ${API_KEY}"
  log "🐳 Container prefix: ${CONTAINER_PREFIX}"

  if [[ "$DISABLE_AUTH_ROTATION" == "true" ]]; then
    log "🔒 Auth rotation: disabled"
  else
    log "🔁 Auth rotation: enabled"
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    log "🧪 Dry run mode was enabled. No containers were started."
  else
    docker ps --filter "name=^${CONTAINER_PREFIX}-" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
  fi
}

main() {
  parse_args "$@"

  if [[ -n "${IMAGE_NAME:-}" && "$IMAGE_NAME" != "$DEFAULT_IMAGE_NAME" && "$IMAGE_NAME_SOURCE" == "default" ]]; then
    IMAGE_NAME_SOURCE="env"
  fi

  require_integer "BASE_API_PORT" "$BASE_API_PORT"
  require_integer "BASE_STREAM_PORT" "$BASE_STREAM_PORT"
  require_integer "MEMORY_PER_INSTANCE_GB" "$MEMORY_PER_INSTANCE_GB"

  validate_paths
  check_docker
  discover_profiles

  log "🔍 Found profiles: ${#PROFILE_FILES[@]} in $PROFILE_DIR"
  print_memory_warning
  confirm_launch

  local idx profile_path profile_basename profile_name container_name api_port stream_port

  for idx in "${!PROFILE_FILES[@]}"; do
    profile_path="${PROFILE_FILES[$idx]}"
    profile_basename="$(basename "$profile_path")"
    profile_name="${profile_basename%.json}"
    container_name="$(sanitize_name "${CONTAINER_PREFIX}-${profile_name}")"
    api_port=$((BASE_API_PORT + idx))
    stream_port=$((BASE_STREAM_PORT + idx))

    prepare_container_ports "$container_name" "$api_port" "$stream_port"
    launch_container "$profile_path" "$profile_name" "$api_port" "$stream_port" "$container_name"
  done

  print_summary
}

main "$@"
