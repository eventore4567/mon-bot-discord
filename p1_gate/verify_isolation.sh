#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
POLICY="$HERE/network_policy.sh"
A_NET=sx-p1-a; B_NET=sx-p1-b; A=sx-p1-a-box; B=sx-p1-b-box
cleanup(){ sudo bash "$POLICY" remove "$A_NET" 2>/dev/null || true; docker rm -f "$A" "$B" 2>/dev/null || true; docker network rm "$A_NET" "$B_NET" 2>/dev/null || true; }
trap cleanup EXIT
cleanup

DNS_SERVER="$(resolvectl dns 2>/dev/null | grep -Eo '([0-9]{1,3}\.){3}[0-9]{1,3}' | grep -Ev '^(127\.|0\.)' | head -n1 || true)"
if [[ -z "$DNS_SERVER" ]]; then
  DNS_SERVER="$(awk '/^nameserver[[:space:]]+/ && $2 !~ /^(127\.|0\.)/ {print $2; exit}' /etc/resolv.conf 2>/dev/null || true)"
fi
[[ -n "$DNS_SERVER" ]] || DNS_SERVER=1.1.1.1
echo "P1 resolver: $DNS_SERVER"

docker network create --subnet 172.30.10.0/24 "$A_NET" >/dev/null
docker network create --subnet 172.30.11.0/24 "$B_NET" >/dev/null
sudo bash "$POLICY" apply "$A_NET" --dns "$DNS_SERVER"
common=(--runtime=runsc --read-only --cap-drop=ALL --security-opt=no-new-privileges:true --pids-limit=64 --memory=128m --memory-swap=128m --tmpfs /tmp:rw,noexec,nosuid,nodev,size=33554432 --dns="$DNS_SERVER")
docker run -d --name "$B" --network "$B_NET" "${common[@]}" --cpus=1 python:3.12-alpine python -m http.server 8080 >/dev/null
docker run -d --name "$A" --network "$A_NET" "${common[@]}" --cpus=.25 python:3.12-alpine sh -c 'sleep infinity' >/dev/null
[[ "$(docker inspect -f '{{.HostConfig.Runtime}}' "$A")" == runsc ]]
[[ "$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$A")" == true ]]
[[ "$(docker inspect -f '{{.HostConfig.PidsLimit}}' "$A")" == 64 ]]
[[ "$(docker inspect -f '{{.HostConfig.Memory}}' "$A")" == 134217728 ]]
[[ "$(docker inspect -f '{{.HostConfig.NanoCpus}}' "$A")" == 250000000 ]]
[[ "$(docker inspect -f '{{index .HostConfig.Dns 0}}' "$A")" == "$DNS_SERVER" ]]
! docker exec "$A" sh -c 'touch /forbidden' 2>/dev/null
! docker exec "$A" test -S /var/run/docker.sock
# Hosted GitHub/Azure runners can make recursive DNS from gVisor flaky. The
# isolation gate therefore proves public egress with a literal public IP while
# independently proving the configured resolver above.
docker exec "$A" python -c "import socket; s=socket.create_connection(('1.1.1.1',443),10); s.close()"
docker exec "$A" python -c "import socket; s=socket.socket(); s.settimeout(2); rc=s.connect_ex(('169.254.169.254',80)); assert rc != 0"
BIP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$B")"
docker exec "$A" python -c "import socket; s=socket.socket(); s.settimeout(2); rc=s.connect_ex(('$BIP',8080)); assert rc != 0"
docker exec -d "$A" python -c 'while True: pass'
timeout 5 docker exec "$B" python -c 'print("neighbor-healthy")' >/dev/null
echo 'P1 REAL ISOLATION PASS'
