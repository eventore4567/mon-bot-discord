"""EconomyService — Core V2, Phase 4 (docs/core-v2-plan.md).

sell/withdraw/deposit/banque/gamble/rob are each wrapped by a monkeypatch
layer that replaces the command actually running in production
(cogs/integrity_hardening.py::_install_economy for the first five,
cogs/sentrix_v22.py::_install_economy_hardening for rob) — verified by
tracing __code__.co_filename/co_firstlineno on a production-identical boot
(51 extensions), which does not lie the way functools.wraps-copied
__qualname__ does. See docs/core-v2-audit-economy-atomicity.md for the full
per-command evidence.

This extraction changes NO behavior: the five functions below are moved
verbatim (queries, lock, rollback/commit points, return values all
unchanged) out of those two cogs and into a plain, Discord-free module so
they can be tested directly. Both cogs now import and delegate to them
instead of keeping a private copy.
"""
from __future__ import annotations

import logging
import secrets
import time
from typing import Any

from utils.v22_rules import parse_friendly_amount, safe_penalty

logger = logging.getLogger("bot.economy-service")

ROB_COOLDOWN_SECONDS = 3600


async def _fetchone_conn(conn, query: str, params: tuple = ()):
    cur = await conn.execute(query, params)
    try:
        return await cur.fetchone()
    finally:
        await cur.close()


async def atomic_bank_transfer(db, guild_id: int, user_id: int, raw_amount: str, *, deposit: bool):
    """Dépôt/retrait atomique (verrou db._economy_lock). Retourne (statut, montant),
    statut valant "ok", "invalid", "changed", "unavailable" ou "error"."""
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "unavailable", 0
    async with db._economy_lock:
        try:
            await conn.execute(
                "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
                (guild_id, user_id),
            )
            row = await _fetchone_conn(
                conn,
                "SELECT cash,bank FROM economy WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            source = int(row["cash"] if deposit else row["bank"]) if row else 0
            amount = parse_friendly_amount(str(raw_amount), source)
            if amount is None or int(amount) <= 0 or int(amount) > source:
                await conn.commit()
                return "invalid", 0
            amount = int(amount)
            if deposit:
                cur = await conn.execute(
                    "UPDATE economy SET cash=cash-?, bank=bank+? "
                    "WHERE guild_id=? AND user_id=? AND cash>=?",
                    (amount, amount, guild_id, user_id, amount),
                )
                transaction_type = "deposit"
                reason = "Dépôt bancaire"
            else:
                cur = await conn.execute(
                    "UPDATE economy SET cash=cash+?, bank=bank-? "
                    "WHERE guild_id=? AND user_id=? AND bank>=?",
                    (amount, amount, guild_id, user_id, amount),
                )
                transaction_type = "withdraw"
                reason = "Retrait bancaire"
            if cur.rowcount < 1:
                await conn.rollback()
                return "changed", 0
            from database.db import now
            await conn.execute(
                "INSERT INTO economy_transactions "
                "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                "VALUES (?,?,?,?,?,?,?)",
                (guild_id, user_id, user_id, transaction_type, amount, now(), reason),
            )
            await conn.commit()
            return "ok", amount
        except Exception:
            await conn.rollback()
            logger.exception("Transaction banque annulée (deposit=%s).", deposit)
            return "error", 0


async def atomic_sell(db, guild_id: int, user_id: int, item_name: str):
    """Vente atomique (verrou db._economy_lock). Retourne (statut, prix),
    statut valant "ok", "missing", "changed", "unavailable" ou "error"."""
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "unavailable", 0
    async with db._economy_lock:
        try:
            row = await _fetchone_conn(
                conn,
                "SELECT quantity FROM inventory WHERE guild_id=? AND user_id=? AND item_name=?",
                (guild_id, user_id, item_name),
            )
            if not row or int(row["quantity"] or 0) < 1:
                return "missing", 0
            item = await _fetchone_conn(
                conn,
                "SELECT price FROM shop_items WHERE guild_id=? AND name=?",
                (guild_id, item_name),
            )
            price = max(0, int(int(item["price"]) * 0.5)) if item else 10
            cur = await conn.execute(
                "UPDATE inventory SET quantity=quantity-1 "
                "WHERE guild_id=? AND user_id=? AND item_name=? AND quantity>=1",
                (guild_id, user_id, item_name),
            )
            if cur.rowcount < 1:
                await conn.rollback()
                return "changed", 0
            await conn.execute(
                "DELETE FROM inventory WHERE guild_id=? AND user_id=? AND item_name=? AND quantity<=0",
                (guild_id, user_id, item_name),
            )
            await conn.execute(
                "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
                (guild_id, user_id),
            )
            await conn.execute(
                "UPDATE economy SET cash=cash+? WHERE guild_id=? AND user_id=?",
                (price, guild_id, user_id),
            )
            from database.db import now
            await conn.execute(
                "INSERT INTO economy_transactions "
                "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                "VALUES (?,NULL,?,'sell',?,?,?)",
                (guild_id, user_id, price, now(), f"Vente : {item_name}"),
            )
            await conn.commit()
            return "ok", price
        except Exception:
            await conn.rollback()
            logger.exception("Vente atomique annulée.")
            return "error", 0


async def atomic_gamble(db, guild_id: int, user_id: int, amount: int, *, win: bool):
    """Mise atomique (verrou db._economy_lock). Retourne "ok", "invalid",
    "insufficient", "unavailable" ou "error"."""
    if amount <= 0:
        return "invalid"
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "unavailable"
    async with db._economy_lock:
        try:
            await conn.execute(
                "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
                (guild_id, user_id),
            )
            delta = amount if win else -amount
            cur = await conn.execute(
                "UPDATE economy SET cash=cash+? "
                "WHERE guild_id=? AND user_id=? AND cash>=?",
                (delta, guild_id, user_id, amount),
            )
            if cur.rowcount < 1:
                await conn.rollback()
                return "insufficient"
            from database.db import now
            await conn.execute(
                "INSERT INTO economy_transactions "
                "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    guild_id,
                    None if win else user_id,
                    user_id if win else None,
                    "gamble_win" if win else "gamble_loss",
                    amount,
                    now(),
                    "Casino",
                ),
            )
            await conn.commit()
            return "ok"
        except Exception:
            await conn.rollback()
            logger.exception("Mise casino annulée.")
            return "error"


async def atomic_rob(db, guild_id: int, thief_id: int, victim_id: int) -> tuple[str, int]:
    """Tentative de vol atomique (verrou db._economy_lock), identique au
    comportement de cogs/sentrix_v22.py::atomic_rob (partie DB uniquement —
    les vérifications ctx/discord restent dans l'appelant). Retourne
    (statut, valeur) : "cooldown"/secondes_restantes, "poor"/0, "retry"/0,
    "success"/montant_volé, "failed"/amende (0 si portefeuille déjà vide),
    ou "error"/0."""
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "error", 0
    async with db._economy_lock:
        try:
            await conn.execute(
                "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
                (guild_id, thief_id),
            )
            await conn.execute(
                "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
                (guild_id, victim_id),
            )
            actor = await _fetchone_conn(
                conn,
                "SELECT cash,last_rob FROM economy WHERE guild_id=? AND user_id=?",
                (guild_id, thief_id),
            )
            target = await _fetchone_conn(
                conn,
                "SELECT cash FROM economy WHERE guild_id=? AND user_id=?",
                (guild_id, victim_id),
            )
            actor_cash = int(actor["cash"] if actor else 0)
            target_cash = int(target["cash"] if target else 0)
            last_rob = int(actor["last_rob"] if actor else 0)
            now_ts = int(time.time())
            remaining = ROB_COOLDOWN_SECONDS - (now_ts - last_rob) if last_rob else 0
            if remaining > 0:
                await conn.commit()
                return "cooldown", remaining
            if target_cash < 50:
                await conn.commit()
                return "poor", 0

            await conn.execute(
                "UPDATE economy SET last_rob=? WHERE guild_id=? AND user_id=?",
                (now_ts, guild_id, thief_id),
            )
            if secrets.randbelow(100) < 40:
                ceiling = min(target_cash, 300)
                amount = 1 + secrets.randbelow(ceiling)
                debit = await conn.execute(
                    "UPDATE economy SET cash=cash-? WHERE guild_id=? AND user_id=? AND cash>=?",
                    (amount, guild_id, victim_id, amount),
                )
                if debit.rowcount < 1:
                    await conn.rollback()
                    return "retry", 0
                await conn.execute(
                    "UPDATE economy SET cash=cash+? WHERE guild_id=? AND user_id=?",
                    (amount, guild_id, thief_id),
                )
                await conn.execute(
                    "INSERT INTO economy_transactions "
                    "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (guild_id, victim_id, thief_id, "rob", amount, now_ts, "Vol réussi V2.2"),
                )
                await conn.commit()
                return "success", amount

            requested = 20 + secrets.randbelow(81)
            penalty = safe_penalty(actor_cash, requested)
            if penalty:
                await conn.execute(
                    "UPDATE economy SET cash=cash-? WHERE guild_id=? AND user_id=? AND cash>=?",
                    (penalty, guild_id, thief_id, penalty),
                )
                await conn.execute(
                    "INSERT INTO economy_transactions "
                    "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                    "VALUES (?,?,NULL,?,?,?,?)",
                    (guild_id, thief_id, "rob_fail", penalty, now_ts, "Vol raté, amende V2.2"),
                )
            await conn.commit()
            return "failed", penalty
        except Exception:
            await conn.rollback()
            logger.exception("V2.2 : transaction +rob annulée.")
            return "error", 0
