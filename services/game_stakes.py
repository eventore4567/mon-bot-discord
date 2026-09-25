"""Mises de jeu : réservation, règlement, remboursement — atomiques et idempotents.

Pourquoi ce service existe. Le premier jet de ``+bomb`` ne prélevait la mise
qu'au moment de perdre. Économiquement l'espérance est la même, mais la faille
est réelle et Jayden l'a vue : un joueur avec 100 peut ouvrir trois grilles à
100 avant qu'aucune ne se résolve, puisque rien n'a encore été débité. Il mise
trois fois le même argent.

La mise est donc RÉSERVÉE au début de la manche :

    ouvrir   100 →  solde −100
    bombe        →  rien de plus
    encaisser x1,66 → solde +166
    profit net   →  +66

Quatre garanties, toutes vérifiées par les tests :

**Idempotence.** ``game_id`` est la clé primaire de ``game_stakes``. Rejouer la
même réservation ne débite pas deux fois, régler deux fois ne paie pas deux
fois : la transition d'état n'a lieu que depuis ``open``.

**Pas de double réservation.** Le débit et l'enregistrement de la mise vivent
dans la même transaction, sous le verrou d'économie. Deux ``+bomb 100`` lancés
à la même milliseconde avec 100 en poche : un seul passe.

**Reprise après redémarrage.** Une manche interrompue laisse une mise ``open``
en base. ``rembourser_mises_orphelines`` les rend au démarrage — sans ce
balayage, l'argent resterait bloqué dans une partie qui n'existe plus.

**Rejouer crée une nouvelle manche.** Un ``game_id`` est tiré par partie ; il
n'est jamais réutilisé, donc une relance ne peut pas régler l'ancienne.
"""
from __future__ import annotations

import logging
import secrets

logger = logging.getLogger("bot.game-stakes")

OUVERTE = "open"
GAGNEE = "won"
PERDUE = "lost"
REMBOURSEE = "refunded"

# Une manche laissée ouverte au-delà de ce délai n'a plus de vue vivante en face :
# son message a expiré, le process a peut-être redémarré. On rend la mise.
ORPHELINE_APRES_SECONDES = 3600


def nouvel_identifiant(game_name: str) -> str:
    """Identifiant unique de manche, qui sert aussi de clé d'idempotence."""
    return f"{game_name}-{secrets.token_hex(8)}"


async def ouvrir_mise(
    db, guild_id: int, user_id: int, game_name: str, montant: int, game_id: str
) -> str:
    """Réserve la mise : débite et enregistre la manche, ou ne fait rien.

    Retourne "ok", "invalid", "duplicate", "insufficient", "unavailable" ou
    "error". Le débit et l'enregistrement sont dans la MÊME transaction : sans
    ça, un crash entre les deux laisserait soit de l'argent perdu, soit une
    manche gratuite.
    """
    montant = int(montant)
    if montant <= 0:
        return "invalid"
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "unavailable"
    from database.db import now

    async with db._economy_lock:
        try:
            cur = await conn.execute(
                "INSERT OR IGNORE INTO game_stakes "
                "(game_id, guild_id, user_id, game_name, amount, state, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (game_id, guild_id, user_id, game_name, montant, OUVERTE, now()),
            )
            if cur.rowcount < 1:
                # Le game_id existe déjà : c'est un rejeu, pas une nouvelle mise.
                await conn.rollback()
                return "duplicate"

            await conn.execute(
                "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
                (guild_id, user_id),
            )
            debit = await conn.execute(
                "UPDATE economy SET cash=cash-? WHERE guild_id=? AND user_id=? AND cash>=?",
                (montant, guild_id, user_id, montant),
            )
            if debit.rowcount < 1:
                # Solde insuffisant : la manche ne doit pas exister du tout.
                await conn.rollback()
                return "insufficient"

            await conn.execute(
                "INSERT INTO economy_transactions "
                "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                "VALUES (?,?,?,?,?,?,?)",
                (guild_id, user_id, None, "game_stake", montant, now(), f"Mise {game_name}"),
            )
            await conn.commit()
            return "ok"
        except Exception:
            await conn.rollback()
            logger.exception("Réservation de mise annulée (%s).", game_id)
            return "error"


async def _regler(db, game_id: str, etat: str, credit: int) -> str:
    """Transition depuis ``open`` uniquement, plus le crédit éventuel.

    La condition ``state = 'open'`` dans le UPDATE est ce qui rend l'opération
    idempotente : un deuxième règlement ne trouve plus de ligne à changer et ne
    crédite rien.
    """
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "unavailable"
    from database.db import now

    async with db._economy_lock:
        try:
            cur = await conn.execute("SELECT * FROM game_stakes WHERE game_id=?", (game_id,))
            ligne = await cur.fetchone()
            if ligne is None:
                await conn.rollback()
                return "unknown"
            if ligne["state"] != OUVERTE:
                await conn.rollback()
                return "already_settled"

            maj = await conn.execute(
                "UPDATE game_stakes SET state=?, payout=?, settled_at=? "
                "WHERE game_id=? AND state=?",
                (etat, int(credit), now(), game_id, OUVERTE),
            )
            if maj.rowcount < 1:
                await conn.rollback()
                return "already_settled"

            if credit > 0:
                await conn.execute(
                    "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
                    (ligne["guild_id"], ligne["user_id"]),
                )
                await conn.execute(
                    "UPDATE economy SET cash=cash+? WHERE guild_id=? AND user_id=?",
                    (int(credit), ligne["guild_id"], ligne["user_id"]),
                )
                await conn.execute(
                    "INSERT INTO economy_transactions "
                    "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        ligne["guild_id"], None, ligne["user_id"],
                        "game_payout" if etat == GAGNEE else "game_refund",
                        int(credit), now(),
                        f"{'Gain' if etat == GAGNEE else 'Remboursement'} {ligne['game_name']}",
                    ),
                )
            await conn.commit()
            return "ok"
        except Exception:
            await conn.rollback()
            logger.exception("Règlement de mise annulé (%s).", game_id)
            return "error"


async def regler_gain(db, game_id: str, retour_total: int) -> str:
    """Manche gagnée : ``retour_total`` est la mise ET le profit.

    On crédite le retour complet parce que la mise a été débitée à l'ouverture.
    Créditer seulement le profit reviendrait à confisquer la mise d'un gagnant.
    """
    return await _regler(db, game_id, GAGNEE, max(0, int(retour_total)))


async def regler_perte(db, game_id: str) -> str:
    """Manche perdue : rien à débiter, la mise est déjà partie à l'ouverture."""
    return await _regler(db, game_id, PERDUE, 0)


async def rembourser_mise(db, game_id: str) -> str:
    """Rend la mise : erreur technique, expiration, manche jamais démarrée.

    C'est le comportement défini pour un timeout sans coup joué et pour toute
    panne survenue après la réservation mais avant que le joueur ait pu jouer.
    """
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "unavailable"
    cur = await conn.execute("SELECT amount FROM game_stakes WHERE game_id=?", (game_id,))
    ligne = await cur.fetchone()
    if ligne is None:
        return "unknown"
    return await _regler(db, game_id, REMBOURSEE, int(ligne["amount"]))


async def mise_ouverte(db, game_id: str):
    """La mise si elle est encore ouverte, sinon None. Pour les vérifications."""
    conn = getattr(db, "_conn", None)
    if conn is None:
        return None
    cur = await conn.execute(
        "SELECT * FROM game_stakes WHERE game_id=? AND state=?", (game_id, OUVERTE)
    )
    return await cur.fetchone()


async def rembourser_mises_orphelines(db, *, age_minimum: int = ORPHELINE_APRES_SECONDES) -> int:
    """Rend les mises restées ouvertes — redémarrage, crash, message perdu.

    Sans ce balayage au démarrage, l'argent d'une manche interrompue resterait
    bloqué dans une partie qui n'existe plus : le joueur l'aurait simplement
    perdu, sans avoir joué.
    """
    conn = getattr(db, "_conn", None)
    if conn is None:
        return 0
    from database.db import now

    cur = await conn.execute(
        "SELECT game_id FROM game_stakes WHERE state=? AND created_at <= ?",
        (OUVERTE, now() - int(age_minimum)),
    )
    orphelines = [ligne["game_id"] for ligne in await cur.fetchall()]
    rendues = 0
    for game_id in orphelines:
        if await rembourser_mise(db, game_id) == "ok":
            rendues += 1
    if rendues:
        logger.info("%s mise(s) orpheline(s) remboursée(s) au démarrage.", rendues)
    return rendues


__all__ = [
    "OUVERTE", "GAGNEE", "PERDUE", "REMBOURSEE",
    "nouvel_identifiant", "ouvrir_mise", "regler_gain", "regler_perte",
    "rembourser_mise", "mise_ouverte", "rembourser_mises_orphelines",
]
