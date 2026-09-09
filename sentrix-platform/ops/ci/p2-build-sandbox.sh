#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
NET="sentrix-build-ci-${RANDOM}-${RANDOM}"
cleanup(){
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
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

# 2) Exercise the SAME network posture as the production dependency worker:
# dedicated bridge, ICC disabled, SentriX-managed label, then host egress policy.
docker network create \
  --driver bridge \
  --opt com.docker.network.bridge.enable_icc=false \
  --label sentrix.managed=true \
  --label sentrix.purpose=builder \
  "$NET" >/dev/null
"$ROOT/ops/execution/apply-egress-policy.sh" docker "203.0.113.0/24"

test "$(docker network inspect --format '{{ index .Labels "sentrix.managed" }}' "$NET")" = "true"
iptables -S SENTRIX-EGRESS | grep -q '169.254.0.0/16'
iptables -S SENTRIX-EGRESS | grep -q '10.0.0.0/8'
iptables -S SENTRIX-EGRESS | grep -q '100.64.0.0/10'

# Host/control-plane secrets must not enter the build environment.  Unlike the
# old proof, this is NOT --network=none: the sandbox is attached to the real
# managed builder bridge and the firewall itself must reject private/metadata
# destinations.
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
    "private_network_reachable": reachable("10.0.0.1", 443),
    "metadata_reachable": reachable("169.254.169.254", 80),
    "cgnat_reachable": reachable("100.64.0.1", 443),
}, sort_keys=True))
PY

export SENTRIX_TENANT_SECRET='host-only-never-pass-me'
export DATABASE_URL='postgresql://host-only'
OUT="$(docker run --rm \
  --runtime=runsc --read-only --cap-drop=ALL --security-opt=no-new-privileges:true \
  --pids-limit=64 --memory=128m --memory-swap=128m --cpus=.25 --network="$NET" \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=33554432 \
  --mount type=bind,src="$TMP/probe",dst=/src,readonly \
  python:3.12-alpine python /src/probe.py)"
echo "$OUT"
PROBE_OUT="$OUT" python - <<'PY'
import json, os
x=json.loads(os.environ["PROBE_OUT"])
assert x == {
    "cgnat_reachable": False,
    "database_url_visible": False,
    "docker_socket": False,
    "metadata_reachable": False,
    "private_network_reachable": False,
    "tenant_secret_visible": False,
}, x
PY

# --rm means no build sandbox remains after the worker exits.
test -z "$(docker ps -a --filter label=sentrix.phase=p2 --format '{{.ID}}')"
echo 'P2 BUILD SANDBOX PASS'
