"""Simulateur de charge hors-ligne pour SentriX.

But : mesurer la capacité de la boucle asyncio et la pression de commandes sans envoyer
une seule requête à Discord, OpenAI, Railway ou un autre service externe.

Exemples :
    python tools/load_test_sentrix.py --users 2000 --commands 200000 --profile core
    python tools/load_test_sentrix.py --users 20000 --commands 200000 --profile heavy

Le résultat est un benchmark SYNTHÉTIQUE. Il ne représente pas les rate limits Discord,
la latence réseau, OpenAI, Lavalink/YouTube ou le vrai CPU/RAM Railway.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import random
import statistics
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandKind:
    name: str
    weight: float
    min_ms: float
    max_ms: float
    fail_rate: float = 0.0


PROFILES: dict[str, tuple[CommandKind, ...]] = {
    # Profil conseillé pour vérifier le moteur interne : même variété que mixed, mais
    # AUCUNE erreur injectée volontairement. Toute erreur affichée vient donc du test lui-même.
    "core": (
        CommandKind("cache/read", 0.35, 0.15, 1.2),
        CommandKind("utility", 0.20, 0.5, 3.0),
        CommandKind("db-read", 0.16, 1.0, 6.0),
        CommandKind("db-write/log", 0.12, 2.0, 10.0),
        CommandKind("moderation", 0.10, 3.0, 15.0),
        CommandKind("heavy-local", 0.05, 10.0, 40.0),
        CommandKind("ai-external-simulated", 0.02, 80.0, 250.0),
    ),
    # Profil historique : inclut volontairement un faible taux d'échecs externes simulés.
    "mixed": (
        CommandKind("cache/read", 0.35, 0.15, 1.2),
        CommandKind("utility", 0.20, 0.5, 3.0),
        CommandKind("db-read", 0.16, 1.0, 6.0),
        CommandKind("db-write/log", 0.12, 2.0, 10.0),
        CommandKind("moderation", 0.10, 3.0, 15.0),
        CommandKind("heavy-local", 0.05, 10.0, 40.0),
        CommandKind("ai-external-simulated", 0.02, 80.0, 250.0, 0.002),
    ),
    "fast": (
        CommandKind("cache/read", 0.60, 0.10, 0.8),
        CommandKind("utility", 0.25, 0.3, 2.0),
        CommandKind("db-read", 0.10, 0.8, 4.0),
        CommandKind("db-write/log", 0.05, 1.5, 6.0),
    ),
    "heavy": (
        CommandKind("db-read", 0.20, 2.0, 10.0),
        CommandKind("db-write/log", 0.25, 4.0, 20.0),
        CommandKind("moderation", 0.20, 6.0, 30.0),
        CommandKind("heavy-local", 0.20, 20.0, 80.0),
        CommandKind("ai-external-simulated", 0.15, 100.0, 350.0, 0.003),
    ),
}


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * p
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return values[lo]
    frac = rank - lo
    return values[lo] * (1.0 - frac) + values[hi] * frac


def choose_kind(profile: tuple[CommandKind, ...]) -> CommandKind:
    r = random.random()
    acc = 0.0
    for kind in profile:
        acc += kind.weight
        if r <= acc:
            return kind
    return profile[-1]


async def simulated_command(kind: CommandKind) -> None:
    await asyncio.sleep(random.uniform(kind.min_ms, kind.max_ms) / 1000.0)
    if kind.fail_rate and random.random() < kind.fail_rate:
        raise RuntimeError("synthetic failure")


async def run_benchmark(users: int, commands: int, profile_name: str, seed: int) -> dict:
    random.seed(seed)
    profile = PROFILES[profile_name]
    queue: asyncio.Queue[tuple[int, float] | None] = asyncio.Queue(maxsize=max(users * 4, 1000))

    latencies_ms: list[float] = []
    service_ms: list[float] = []
    errors = 0
    by_kind: dict[str, int] = {kind.name: 0 for kind in profile}
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal errors
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                return
            _, queued_at = item
            kind = choose_kind(profile)
            started = time.perf_counter()
            failed = False
            try:
                await simulated_command(kind)
            except Exception:
                failed = True
            finished = time.perf_counter()
            async with lock:
                latencies_ms.append((finished - queued_at) * 1000)
                service_ms.append((finished - started) * 1000)
                by_kind[kind.name] += 1
                if failed:
                    errors += 1
            queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(users)]
    started_at = time.perf_counter()

    for command_id in range(commands):
        await queue.put((command_id, time.perf_counter()))

    await queue.join()
    duration = time.perf_counter() - started_at

    for _ in workers:
        await queue.put(None)
    await asyncio.gather(*workers)

    return {
        "users": users,
        "commands": commands,
        "profile": profile_name,
        "duration_s": duration,
        "throughput": commands / duration if duration else 0.0,
        "errors": errors,
        "error_rate": errors / commands if commands else 0.0,
        "lat_avg": statistics.fmean(latencies_ms) if latencies_ms else 0.0,
        "lat_p50": percentile(latencies_ms, 0.50),
        "lat_p95": percentile(latencies_ms, 0.95),
        "lat_p99": percentile(latencies_ms, 0.99),
        "service_avg": statistics.fmean(service_ms) if service_ms else 0.0,
        "service_p95": percentile(service_ms, 0.95),
        "by_kind": by_kind,
    }


def print_report(result: dict) -> None:
    print("\n=== SENTRIX LOAD TEST — OFFLINE ===")
    print(f"Profil               : {result['profile']}")
    print(f"Utilisateurs virtuels: {result['users']:,}".replace(",", " "))
    print(f"Commandes simulées   : {result['commands']:,}".replace(",", " "))
    print(f"Durée                : {result['duration_s']:.2f} s")
    print(f"Débit                : {result['throughput']:,.0f} cmd/s".replace(",", " "))
    print(f"Erreurs synthétiques : {result['errors']} ({result['error_rate'] * 100:.3f} %)")
    print("\nLatence totale (file + traitement)")
    print(f"  moyenne : {result['lat_avg']:.2f} ms")
    print(f"  p50     : {result['lat_p50']:.2f} ms")
    print(f"  p95     : {result['lat_p95']:.2f} ms")
    print(f"  p99     : {result['lat_p99']:.2f} ms")
    print("\nTemps de traitement simulé")
    print(f"  moyenne : {result['service_avg']:.2f} ms")
    print(f"  p95     : {result['service_p95']:.2f} ms")
    print("\nRépartition")
    for name, count in result["by_kind"].items():
        print(f"  {name:<24} {count:>8}")
    print("\nIMPORTANT : ce benchmark ne teste PAS les rate limits Discord ni les API externes.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulateur de charge interne SentriX")
    parser.add_argument("--users", type=int, default=2000, help="nombre de workers/utilisateurs virtuels")
    parser.add_argument("--commands", type=int, default=200000, help="nombre total de commandes")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="core")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not 1 <= args.users <= 50000:
        parser.error("--users doit être compris entre 1 et 50000")
    if not 1 <= args.commands <= 2_000_000:
        parser.error("--commands doit être compris entre 1 et 2000000")
    return args


if __name__ == "__main__":
    args = parse_args()
    result = asyncio.run(run_benchmark(args.users, args.commands, args.profile, args.seed))
    print_report(result)
