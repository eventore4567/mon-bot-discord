#!/usr/bin/env bash
set -euo pipefail

# Installation recommandee par la documentation officielle gVisor : depot APT.
# Linux amd64/arm64 uniquement.
apt-get update
apt-get install -y --no-install-recommends apt-transport-https ca-certificates curl gnupg
curl -fsSL https://gvisor.dev/archive.key | gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" \
  > /etc/apt/sources.list.d/gvisor.list
apt-get update
apt-get install -y --no-install-recommends runsc
runsc install
if command -v systemctl >/dev/null 2>&1; then
  systemctl restart docker
else
  kill -HUP "$(pidof dockerd)"
fi
docker run --rm --runtime=runsc hello-world >/dev/null
