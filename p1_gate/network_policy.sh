#!/usr/bin/env bash
set -euo pipefail
op="${1:-}"; net="${2:-}"; shift 2 || true
[[ -n "$net" ]] || exit 2
subnet="$(docker network inspect -f '{{(index .IPAM.Config 0).Subnet}}' "$net")"
hash="$(printf '%s' "$net" | sha256sum | cut -c1-12 | tr '[:lower:]' '[:upper:]')"
chain="SX_${hash}"
remove(){ iptables -D DOCKER-USER -s "$subnet" -j "$chain" 2>/dev/null || true; iptables -F "$chain" 2>/dev/null || true; iptables -X "$chain" 2>/dev/null || true; }
if [[ "$op" == remove ]]; then remove; exit 0; fi
[[ "$op" == apply ]]
iptables -N "$chain" 2>/dev/null || true
iptables -F "$chain"
iptables -C DOCKER-USER -s "$subnet" -j "$chain" 2>/dev/null || iptables -I DOCKER-USER 1 -s "$subnet" -j "$chain"
iptables -A "$chain" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
for cidr in 169.254.169.254/32 169.254.0.0/16 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 127.0.0.0/8 0.0.0.0/8 224.0.0.0/4 240.0.0.0/4; do
  iptables -A "$chain" -d "$cidr" -j REJECT
done
for cidr in "$@"; do [[ -n "$cidr" ]] && iptables -A "$chain" -d "$cidr" -j REJECT; done
iptables -A "$chain" -j RETURN
