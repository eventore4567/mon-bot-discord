#!/usr/bin/env python3
"""Credential-gated live Discord proofs for P3 and P6.

No secret is printed. These probes intentionally consume real Discord IDENTIFY
budget, so they only run from the manual live workflow with dedicated test apps.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx
from websockets.asyncio.client import connect

from services.identify_broker.broker import IdentifyBroker
from services.identify_broker.model import IdentifyBudget
from services.identify_broker.store import MemoryIdentifyStore

API = "https://discord.com/api/v10"


@dataclass(frozen=True, slots=True)
class GatewayBudget:
    application_id: str
    url: str
    total: int
    remaining: int
    reset_after: int
    max_concurrency: int


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bot {token}", "User-Agent": "SentriX-Live-Gate/1.0"}


def fetch_budget(token: str) -> GatewayBudget:
    with httpx.Client(timeout=15.0, headers=_headers(token)) as client:
        app_response = client.get(f"{API}/oauth2/applications/@me")
        app_response.raise_for_status()
        gateway_response = client.get(f"{API}/gateway/bot")
        gateway_response.raise_for_status()
    app = app_response.json()
    gateway = gateway_response.json()
    limit = gateway["session_start_limit"]
    return GatewayBudget(
        application_id=str(app["id"]),
        url=str(gateway["url"]),
        total=int(limit["total"]),
        remaining=int(limit["remaining"]),
        reset_after=int(limit["reset_after"]),
        max_concurrency=int(limit["max_concurrency"]),
    )


async def identify_ready(token: str, gateway_url: str, *, hold_seconds: float = 0.0) -> None:
    url = f"{gateway_url.rstrip('/')}?v=10&encoding=json"
    async with connect(url, open_timeout=15, close_timeout=10) as websocket:
        hello_raw = await asyncio.wait_for(websocket.recv(), timeout=15)
        hello = json.loads(str(hello_raw))
        if hello.get("op") != 10:
            raise RuntimeError(f"expected Discord HELLO opcode 10, got {hello.get('op')!r}")
        heartbeat_seconds = float(hello["d"]["heartbeat_interval"]) / 1000.0

        # Discord permits an immediate heartbeat request response; sending one
        # here proves the connection is alive before IDENTIFY.
        await websocket.send(json.dumps({"op": 1, "d": None}))
        await websocket.send(
            json.dumps(
                {
                    "op": 2,
                    "d": {
                        "token": token,
                        "intents": 0,
                        "properties": {
                            "os": "linux",
                            "browser": "sentrix-live-gate",
                            "device": "sentrix-live-gate",
                        },
                    },
                }
            )
        )

        ready = False
        for _ in range(30):
            raw = await asyncio.wait_for(websocket.recv(), timeout=max(15.0, heartbeat_seconds))
            payload: dict[str, Any] = json.loads(str(raw))
            if payload.get("op") == 0 and payload.get("t") == "READY":
                ready = True
                break
            if payload.get("op") == 9:
                raise RuntimeError("Discord returned INVALID_SESSION during live gate")
        if not ready:
            raise RuntimeError("Discord READY was not observed")

        if hold_seconds <= 0:
            return

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(heartbeat_seconds)
                await websocket.send(json.dumps({"op": 1, "d": None}))

        async def drain() -> None:
            async for raw in websocket:
                payload = json.loads(str(raw))
                if payload.get("op") in {7, 9}:
                    raise RuntimeError(f"Discord ended canary session with opcode {payload.get('op')}")

        heartbeat_task = asyncio.create_task(heartbeat())
        drain_task = asyncio.create_task(drain())
        try:
            await asyncio.sleep(hold_seconds)
            for task in (heartbeat_task, drain_task):
                if task.done() and not task.cancelled():
                    exc = task.exception()
                    if exc is not None:
                        raise exc
        finally:
            heartbeat_task.cancel()
            drain_task.cancel()
            await asyncio.gather(heartbeat_task, drain_task, return_exceptions=True)


def _require_identify_headroom(budget: GatewayBudget) -> None:
    # Leave a meaningful emergency reserve. The live gate must never test with
    # an application already close to exhausting its daily session-start limit.
    minimum = int(os.environ.get("SENTRIX_LIVE_MIN_REMAINING", "10"))
    if budget.remaining < minimum:
        raise RuntimeError(
            f"refusing live IDENTIFY: only {budget.remaining} session starts remain (< {minimum})"
        )


def p3(token: str) -> None:
    before = fetch_budget(token)
    _require_identify_headroom(before)

    local_budget = IdentifyBudget(
        application_id=before.application_id,
        total=before.total,
        remaining_local=before.remaining,
        reset_after_ms=before.reset_after,
        max_concurrency=before.max_concurrency,
    )
    store = MemoryIdentifyStore(budgets={before.application_id: local_budget})
    broker = IdentifyBroker(store)
    reservation = broker.reserve(before.application_id, 0)

    # This is the invariant under test: persist/consume locally before opcode 2.
    broker.persist_identify_sent(reservation.id)
    asyncio.run(identify_ready(token, before.url))
    broker.ready(reservation.id)

    after = fetch_budget(token)
    broker.reconcile_discord(before.application_id, after.remaining)
    if after.remaining != before.remaining - 1:
        raise RuntimeError(
            "Discord session_start_limit did not decrease by exactly one "
            f"({before.remaining} -> {after.remaining})"
        )
    if local_budget.remaining_local != after.remaining:
        raise RuntimeError(
            "IdentifyBroker counter differs from Discord "
            f"(local={local_budget.remaining_local}, discord={after.remaining})"
        )
    print(
        json.dumps(
            {
                "gate": "P3",
                "application_id": before.application_id,
                "discord_before": before.remaining,
                "discord_after": after.remaining,
                "local_after": local_budget.remaining_local,
                "result": "PASS",
            },
            sort_keys=True,
        )
    )


def p6(canary_token: str, prod_token: str, bake_seconds: float) -> None:
    canary_before = fetch_budget(canary_token)
    prod_before = fetch_budget(prod_token)
    _require_identify_headroom(canary_before)
    if canary_before.application_id == prod_before.application_id:
        raise RuntimeError("P6 requires distinct Discord applications for canary and prod")

    asyncio.run(identify_ready(canary_token, canary_before.url, hold_seconds=bake_seconds))

    canary_after = fetch_budget(canary_token)
    prod_after = fetch_budget(prod_token)
    if canary_after.remaining != canary_before.remaining - 1:
        raise RuntimeError("canary application did not consume exactly one IDENTIFY")
    if prod_after.remaining != prod_before.remaining:
        raise RuntimeError("prod application IDENTIFY budget changed during canary bake")
    print(
        json.dumps(
            {
                "gate": "P6",
                "canary_application_id": canary_before.application_id,
                "prod_application_id": prod_before.application_id,
                "bake_seconds": bake_seconds,
                "canary_before": canary_before.remaining,
                "canary_after": canary_after.remaining,
                "prod_before": prod_before.remaining,
                "prod_after": prod_after.remaining,
                "result": "PASS",
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="gate", required=True)
    sub.add_parser("p3")
    p6_parser = sub.add_parser("p6")
    p6_parser.add_argument("--bake-seconds", type=float, default=1800.0)
    args = parser.parse_args()

    if args.gate == "p3":
        token = os.environ.get("SENTRIX_P3_DISCORD_TOKEN", "")
        if not token:
            raise SystemExit("SENTRIX_P3_DISCORD_TOKEN is required")
        p3(token)
        return

    canary_token = os.environ.get("SENTRIX_P6_CANARY_TOKEN", "")
    prod_token = os.environ.get("SENTRIX_P6_PROD_TOKEN", "")
    if not canary_token or not prod_token:
        raise SystemExit("SENTRIX_P6_CANARY_TOKEN and SENTRIX_P6_PROD_TOKEN are required")
    p6(canary_token, prod_token, args.bake_seconds)


if __name__ == "__main__":
    main()
