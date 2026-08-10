#!/usr/bin/env bash
set -euo pipefail
C="sx-p5-secret-$RANDOM"
SECRET='sentrix-test-secret-not-in-inspect-9f4d2'
cleanup(){ docker rm -f "$C" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$C" --runtime=runsc --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges:true --pids-limit=64 --memory=128m --memory-swap=128m \
  --network=none --tmpfs /run/secrets:rw,noexec,nosuid,nodev,size=1048576 \
  python:3.12-alpine sh -c 'sleep 300' >/dev/null

# Secret enters through stdin, not argv/env/container config, and lands on tmpfs.
printf '%s' "$SECRET" | docker exec -i "$C" sh -c 'umask 077; cat > /run/secrets/discord_token; chmod 400 /run/secrets/discord_token'

test "$(docker exec "$C" cat /run/secrets/discord_token)" = "$SECRET"
test "$(docker exec "$C" stat -c '%a' /run/secrets/discord_token)" = 400
! docker inspect "$C" | grep -Fq "$SECRET"
! docker exec "$C" sh -c 'tr "\0" "\n" < /proc/1/environ' | grep -Fq "$SECRET"
! docker logs "$C" 2>&1 | grep -Fq "$SECRET"

echo 'P5 TMPFS SECRET PASS'
