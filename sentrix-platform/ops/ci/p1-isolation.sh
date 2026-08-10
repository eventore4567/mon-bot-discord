#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
ID_A="01930000-0000-7000-8000-00000000000a"
ID_B="01930000-0000-7000-8000-00000000000b"
cleanup() {
  docker rm -f "sentrix-$ID_A" "sentrix-$ID_B" 2>/dev/null || true
  docker network rm "sentrix-net-$ID_A" "sentrix-net-$ID_B" 2>/dev/null || true
  "$ROOT/ops/execution/apply-egress-policy.sh" docker "" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create --driver bridge --opt com.docker.network.bridge.enable_icc=false --label sentrix.managed=true "sentrix-net-$ID_A" >/dev/null
docker network create --driver bridge --opt com.docker.network.bridge.enable_icc=false --label sentrix.managed=true "sentrix-net-$ID_B" >/dev/null
"$ROOT/ops/execution/apply-egress-policy.sh" docker "" >/dev/null

docker run -d --name "sentrix-$ID_B" --runtime=runsc --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true --network "sentrix-net-$ID_B" \
  python:3.12-alpine python -m http.server 8080 >/dev/null
IP_B="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "sentrix-$ID_B")"

# HTTPS public autorise.
docker run --rm --runtime=runsc --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --network "sentrix-net-$ID_A" python:3.12-alpine \
  python -c 'import urllib.request; r=urllib.request.urlopen("https://example.com", timeout=10); assert 200 <= r.status < 400'

# Metadata cloud / RFC1918 / sandbox voisin doivent echouer.
for TARGET in "169.254.169.254:80" "10.0.0.1:80" "$IP_B:8080"; do
  HOST="${TARGET%:*}" PORT="${TARGET##*:}"
  docker run --rm --runtime=runsc --read-only --cap-drop ALL --security-opt no-new-privileges:true \
    --network "sentrix-net-$ID_A" -e HOST="$HOST" -e PORT="$PORT" python:3.12-alpine \
    python -c 'import os,socket,sys; s=socket.socket(); s.settimeout(2); rc=s.connect_ex((os.environ["HOST"], int(os.environ["PORT"]))); sys.exit(0 if rc else 1)'
done

echo "P1 ISOLATION PASS: public HTTPS oui, metadata/prive/voisin non"
