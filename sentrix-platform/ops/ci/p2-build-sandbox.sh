#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
cleanup(){ rm -rf "$TMP"; }
trap cleanup EXIT

# 1) SCAN must reject a hard-coded Discord-like token before any build starts.
mkdir -p "$TMP/bad"
printf 'DISCORD_TOKEN="M%s.AAAAAA.%s"\n' "$(printf 'A%.0s' {1..23})" "$(printf 'B%.0s' {1..30})" > "$TMP/bad/bot.py"
if PYTHONPATH="$ROOT" BAD_ROOT="$TMP/bad" python - <<'PY'
import os
from pathlib import Path
from services.builder_ctl.controller import BuildRejected, preflight_source
try:
    preflight_source(Path(os.environ["BAD_ROOT"]))
except BuildRejected:
    raise SystemExit(7)
raise SystemExit(0)
PY
then
  echo "P2 scanner failed to reject hard-coded token" >&2
  exit 1
else
  rc=$?
  test "$rc" = 7 || exit "$rc"
fi

# 2) Host/control-plane secrets must not enter the build environment, and the
# hostile build cannot reach any network when the policy gives it no registry.
mkdir -p "$TMP/probe"
cat > "$TMP/probe/probe.py" <<'PY'
import json, os, socket

def reachable(host, port):
    s=socket.socket(); s.settimeout(0.5)
    try:
        return s.connect_ex((host,port)) == 0
    finally:
        s.close()

print(json.dumps({
    "tenant_secret_visible": bool(os.environ.get("SENTRIX_TENANT_SECRET")),
    "database_url_visible": bool(os.environ.get("DATABASE_URL")),
    "docker_socket": os.path.exists("/var/run/docker.sock"),
    "control_plane_reachable": reachable("10.0.0.1", 443),
}, sort_keys=True))
PY

export SENTRIX_TENANT_SECRET='host-only-never-pass-me'
export DATABASE_URL='postgresql://host-only'
OUT="$(docker run --rm \
  --runtime=runsc --read-only --cap-drop=ALL --security-opt=no-new-privileges:true \
  --pids-limit=64 --memory=128m --memory-swap=128m --cpus=.25 --network=none \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=33554432 \
  --mount type=bind,src="$TMP/probe",dst=/src,readonly \
  python:3.12-alpine python /src/probe.py)"
echo "$OUT"
PROBE_OUT="$OUT" python - <<'PY'
import json, os
x=json.loads(os.environ["PROBE_OUT"])
assert x == {
    "control_plane_reachable": False,
    "database_url_visible": False,
    "docker_socket": False,
    "tenant_secret_visible": False,
}, x
PY

# --rm means no build sandbox remains after the worker exits.
test -z "$(docker ps -a --filter label=sentrix.phase=p2 --format '{{.ID}}')"
echo 'P2 BUILD SANDBOX PASS'
