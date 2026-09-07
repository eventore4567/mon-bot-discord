#!/usr/bin/env bash
set -euo pipefail

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
ok() { printf 'OK: %s\n' "$*"; }

[[ "$(uname -s)" == "Linux" ]] || fail "SentriX worker requires Linux"
[[ -r /sys/fs/cgroup/cgroup.controllers ]] || fail "cgroups v2 is required"
command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v runsc >/dev/null 2>&1 || fail "gVisor runsc is required"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"

python3 - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit("ERROR: Python 3.12+ is required")
print("OK: Python", sys.version.split()[0])
PY

docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable"
if ! docker info --format '{{json .Runtimes}}' | grep -q 'runsc'; then
  fail "Docker runtime 'runsc' is not registered"
fi

[[ -n "${SENTRIX_CONTROL_PLANE_URL:-}" ]] || fail "SENTRIX_CONTROL_PLANE_URL is missing"
[[ -n "${SENTRIX_NODE_ID:-}" ]] || fail "SENTRIX_NODE_ID is missing"
node_token="${SENTRIX_NODE_TOKEN:-}"
[[ ${#node_token} -ge 16 ]] || fail "SENTRIX_NODE_TOKEN must be at least 16 chars"

install -d -m 0700 /var/lib/sentrix-agent
install -d -m 0755 /etc/sentrix

ok "Linux + cgroups v2"
ok "Docker + gVisor runsc"
ok "SentriX worker environment"
printf 'SentriX worker preflight passed.\n'
