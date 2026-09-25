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

RESERVEE = "reserved"      # débitée, partie pas encore affichée
ACTIVE = "active"          # partie affichée, aucune action du joueur
ENGAGEE = "committed"      # au moins une action significative
GAGNEE = "won"
PERDUE = "lost"
REMBOURSEE = "refunded"

# Les trois états d'où l'on peut encore régler. Toute transition part de l'un
# d'eux : c'est ce qui rend les règlements idempotents.
EN_COURS = (RESERVEE, ACTIVE, ENGAGEE)
TERMINAUX = (GAGNEE, PERDUE, REMBOURSEE)

# Compatibilité : d'anciennes lignes peuvent porter l'état « open » d'avant la
# distinction reserved/active/committed. On les traite comme réservées.
OUVERTE = "open"

# Une manche laissée en cours au-delà de ce délai n'a plus de vue vivante en
# face : son message a expiré, le process a peut-être redémarré.
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
                "(game_id, guild_id, user_id, game_name, amount, state, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (game_id, guild_id, user_id, game_name, montant, RESERVEE, now(), now()),
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


async def _avancer(db, game_id: str, vers: str, depuis: tuple[str, ...], **colonnes) -> str:
    """Fait avancer une manche d'un état en cours vers un autre. Idempotent.

    La condition ``state IN depuis`` dans le UPDATE est ce qui garantit qu'une
    deuxième tentative — deuxième clic, deuxième instance HA, reprise après
    crash — ne trouve plus de ligne à changer et ne fait rien.
    """
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "unavailable"
    from database.db import now

    async with db._economy_lock:
        try:
            champs = ", ".join(f"{cle}=?" for cle in colonnes)
            supplement = f", {champs}" if champs else ""
            marques = ",".join("?" for _ in depuis)
            cur = await conn.execute(
                f"UPDATE game_stakes SET state=?, updated_at=?{supplement} "
                f"WHERE game_id=? AND state IN ({marques})",
                (vers, now(), *colonnes.values(), game_id, *depuis),
            )
            if cur.rowcount < 1:
                await conn.rollback()
                return "no_op"
            await conn.commit()
            return "ok"
        except Exception:
            await conn.rollback()
            logger.exception("Transition de mise annulée (%s -> %s).", game_id, vers)
            return "error"


async def marquer_active(db, game_id: str, message_id: int | None = None) -> str:
    """La partie est affichée : un crash ne la considère plus comme non démarrée."""
    return await _avancer(db, game_id, ACTIVE, (RESERVEE, OUVERTE),
                          **({"message_id": int(message_id)} if message_id else {}))


async def marquer_engagee(db, game_id: str) -> str:
    """Première action significative du joueur.

    À partir d'ici, un redémarrage ne rend PLUS la mise : sinon un crash — ou
    un simple déploiement — annulerait gratuitement une partie mal engagée.
    """
    from database.db import now

    return await _avancer(db, game_id, ENGAGEE, (RESERVEE, ACTIVE, OUVERTE),
                          first_action_at=now())


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
            if ligne["state"] not in (*EN_COURS, OUVERTE):
                await conn.rollback()
                return "already_settled"

            marques = ",".join("?" for _ in (*EN_COURS, OUVERTE))
            maj = await conn.execute(
                f"UPDATE game_stakes SET state=?, payout=?, settled_at=?, updated_at=? "
                f"WHERE game_id=? AND state IN ({marques})",
                (etat, int(credit), now(), now(), game_id, *EN_COURS, OUVERTE),
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
    marques = ",".join("?" for _ in (*EN_COURS, OUVERTE))
    cur = await conn.execute(
        f"SELECT * FROM game_stakes WHERE game_id=? AND state IN ({marques})",
        (game_id, *EN_COURS, OUVERTE),
    )
    return await cur.fetchone()


async def reprendre_mises_interrompues(db, *, age_minimum: int = ORPHELINE_APRES_SECONDES) -> dict:
    """Applique une politique DÉTERMINISTE aux manches qu'un arrêt a coupées.

    Un remboursement automatique de tout ce qui traîne serait un cadeau : une
    partie déjà engagée — plusieurs cases ouvertes, position dangereuse —
    redeviendrait gratuite au moindre redémarrage, et un déploiement rendrait
    leur mise à tous ceux qui étaient en train de perdre.

    La politique dépend donc de ce que le joueur avait réellement fait :

      reserved  → remboursé. La partie n'a jamais été affichée ; il n'a rien vu,
                  il ne paie rien.
      active    → remboursé. La partie s'affichait mais il n'avait pas encore
                  joué : rien ne s'était produit qui vaille sa mise.
      committed → PERDU. Au moins une action significative. La mise reste
                  engagée, exactement comme si la manche s'était terminée sur
                  cette action. Aucun remboursement au seul motif que le
                  processus a redémarré.

    Idempotent et sûr en haute disponibilité : chaque règlement part d'un état
    en cours, donc si le primary et le standby balaient en même temps, un seul
    des deux change la ligne et l'autre obtient « already_settled ».
    """
    conn = getattr(db, "_conn", None)
    if conn is None:
        return {"rembourses": 0, "perdus": 0}
    from database.db import now

    limite = now() - int(age_minimum)
    marques = ",".join("?" for _ in (*EN_COURS, OUVERTE))
    cur = await conn.execute(
        f"SELECT game_id, state FROM game_stakes "
        f"WHERE state IN ({marques}) AND created_at <= ?",
        (*EN_COURS, OUVERTE, limite),
    )
    interrompues = [(l["game_id"], l["state"]) for l in await cur.fetchall()]

    bilan = {"rembourses": 0, "perdus": 0}
    for game_id, etat in interrompues:
        if etat == ENGAGEE:
            if await regler_perte(db, game_id) == "ok":
                bilan["perdus"] += 1
        elif await rembourser_mise(db, game_id) == "ok":
            bilan["rembourses"] += 1

    if bilan["rembourses"] or bilan["perdus"]:
        logger.info(
            "Mises interrompues reprises : %s remboursée(s), %s perdue(s) (parties engagées).",
            bilan["rembourses"], bilan["perdus"],
        )
    return bilan


async def rembourser_mises_orphelines(db, *, age_minimum: int = ORPHELINE_APRES_SECONDES) -> int:
    """Compatibilité : ancien nom, rend le nombre de mises remboursées.

    Conservé parce qu'un appelant existant pourrait encore l'utiliser ; il
    délègue à la politique complète plutôt que de rembourser aveuglément.
    """
    bilan = await reprendre_mises_interrompues(db, age_minimum=age_minimum)
    return bilan["rembourses"]


__all__ = [
    "RESERVEE", "ACTIVE", "ENGAGEE", "GAGNEE", "PERDUE", "REMBOURSEE",
    "EN_COURS", "TERMINAUX", "OUVERTE",
    "nouvel_identifiant", "ouvrir_mise", "marquer_active", "marquer_engagee",
    "regler_gain", "regler_perte", "rembourser_mise", "mise_ouverte",
    "reprendre_mises_interrompues", "rembourser_mises_orphelines",
]
