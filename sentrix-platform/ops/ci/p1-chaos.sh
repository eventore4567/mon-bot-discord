#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
INSTANCE_ID="01930000-0000-7000-8000-000000000001"
NODE_ID="01930000-0000-7000-8000-000000000002"
PORT=18099
TMP="$(mktemp -d)"
CP_PID=""
AGENT_PID=""
cleanup() {
  [[ -z "$AGENT_PID" ]] || kill "$AGENT_PID" 2>/dev/null || true
  [[ -z "$CP_PID" ]] || kill "$CP_PID" 2>/dev/null || true
  docker rm -f "sentrix-$INSTANCE_ID" 2>/dev/null || true
  docker network rm "sentrix-net-$INSTANCE_ID" 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

cat > "$TMP/desired.json" <<JSON
[{"instance_id":"$INSTANCE_ID","desired_state":"running","image_ref":"python:3.12-alpine","command":["python","-c","import time; time.sleep(3600)"],"cpu_millis":250,"memory_mb":128,"pids_limit":64,"generation":1}]
JSON
python tests/p1/fake_control_plane.py --port "$PORT" --desired "$TMP/desired.json" &
CP_PID=$!

export SENTRIX_CONTROL_PLANE_URL="http://127.0.0.1:$PORT"
export SENTRIX_NODE_ID="$NODE_ID"
export SENTRIX_NODE_TOKEN="0123456789abcdef0123456789abcdef"
export SENTRIX_AGENT_CACHE="$TMP/cache.json"
export SENTRIX_AGENT_POLL_SECONDS="1"
export SENTRIX_EGRESS_SCRIPT="$ROOT/ops/execution/apply-egress-policy.sh"
python -m agents.node_agent.main &
AGENT_PID=$!

for _ in $(seq 1 60); do
  CID1="$(docker ps -q --filter "name=^sentrix-$INSTANCE_ID$")"
  [[ -n "$CID1" ]] && break
  sleep 1
done
[[ -n "${CID1:-}" ]] || { echo "sandbox non demarre" >&2; exit 1; }
[[ "$(docker inspect -f '{{.HostConfig.Runtime}}' "$CID1")" == "runsc" ]]
[[ "$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$CID1")" == "true" ]]
[[ "$(docker inspect -f '{{.HostConfig.PidsLimit}}' "$CID1")" == "64" ]]
[[ "$(docker inspect -f '{{.HostConfig.Memory}}' "$CID1")" == "134217728" ]]
[[ "$(docker inspect -f '{{.HostConfig.NanoCpus}}' "$CID1")" == "250000000" ]]

# Le CP tombe. Le bot DOIT continuer a tourner.
kill "$CP_PID"
wait "$CP_PID" 2>/dev/null || true
CP_PID=""
sleep 2
[[ "$(docker inspect -f '{{.State.Running}}' "$CID1")" == "true" ]]

# kill -9 du sandbox pendant que le CP est coupe : le cache local doit suffire
# pour que le reconciler relance une nouvelle instance.
docker kill --signal KILL "$CID1" >/dev/null
for _ in $(seq 1 60); do
  CID2="$(docker ps -q --filter "name=^sentrix-$INSTANCE_ID$")"
  [[ -n "$CID2" && "$CID2" != "$CID1" ]] && break
  sleep 1
done
[[ -n "${CID2:-}" && "$CID2" != "$CID1" ]] || { echo "reconciler n'a pas relance" >&2; exit 1; }

echo "P1 CHAOS PASS: CP outage + kill -9 relance depuis cache"
