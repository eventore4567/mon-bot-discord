#!/usr/bin/env bash
set -euo pipefail

DOCKER_BIN="${1:-docker}"
CONTROL_PLANE_CIDRS="${2:-}"
CHAIN="SENTRIX-EGRESS"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "apply-egress-policy.sh doit etre execute en root" >&2
  exit 70
fi
if ! command -v iptables >/dev/null 2>&1; then
  echo "iptables absent: egress fail-closed" >&2
  exit 71
fi
# Avec le backend nftables experimental de Docker, DOCKER-USER n'existe pas.
# On refuse de continuer plutot que de pretendre isoler les tenants.
if ! iptables -S DOCKER-USER >/dev/null 2>&1; then
  echo "chaine DOCKER-USER absente; utiliser le backend iptables Docker pour P1" >&2
  exit 72
fi

iptables -N "$CHAIN" 2>/dev/null || true
iptables -C DOCKER-USER -j "$CHAIN" 2>/dev/null || iptables -I DOCKER-USER 1 -j "$CHAIN"
iptables -F "$CHAIN"
iptables -A "$CHAIN" -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN

mapfile -t SUBNETS < <(
  "$DOCKER_BIN" network ls -q --filter label=sentrix.managed=true \
    | xargs -r "$DOCKER_BIN" network inspect \
      --format '{{range .IPAM.Config}}{{if .Subnet}}{{.Subnet}}{{"\n"}}{{end}}{{end}}' \
    | awk 'NF' | sort -u
)

IFS=',' read -r -a CP <<< "$CONTROL_PLANE_CIDRS"
for subnet in "${SUBNETS[@]:-}"; do
  [[ -n "$subnet" ]] || continue
  # Metadata cloud, link-local et reseaux prives : interdits depuis tout sandbox.
  for blocked in 169.254.0.0/16 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10; do
    iptables -A "$CHAIN" -s "$subnet" -d "$blocked" -j REJECT --reject-with icmp-port-unreachable
  done
  for blocked in "${CP[@]:-}"; do
    [[ -n "$blocked" ]] || continue
    iptables -A "$CHAIN" -s "$subnet" -d "$blocked" -j REJECT --reject-with icmp-port-unreachable
  done
  # Tout le reste (Internet public) reste autorise.
  iptables -A "$CHAIN" -s "$subnet" -j RETURN
done
iptables -A "$CHAIN" -j RETURN
