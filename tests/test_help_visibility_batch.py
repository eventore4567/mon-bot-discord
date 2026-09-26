"""Audit du 2026-09-09 sur les familles tickets/logs/notifications/server/économie/
niveaux/emoji : une trentaine de commandes réelles, sans remplaçant fonctionnel,
étaient masquées de `+help` par le filet générique d'`apply_surface()` — ni fusionnées
dans `/setup` (contrairement à leurs voisines `logsetup`/`create-logs`/`automod-status`),
ni classées nulle part. Un membre ou un staff qui ne connaissait pas déjà le nom exact
d'une de ces commandes n'avait aucun moyen de la découvrir.

Corrigé en les ajoutant à `HELP_VISIBLE_EXTRA_COMMANDS`, sans toucher au budget slash
(aucune n'est ajoutée à `NORMAL_DIRECT_COMMANDS`)."""
from __future__ import annotations

import unittest

from cogs.command_catalog_cleanup import (
    ADMIN_DIRECT_COMMANDS,
    HELP_VISIBLE_EXTRA_COMMANDS,
    NORMAL_DIRECT_COMMANDS,
)


class HelpVisibilityBatchTests(unittest.TestCase):
    def test_commandes_precedemment_orphelines_sont_desormais_listees(self):
        expected = {
            "notifs-ping", "notifs-list", "notifs-remove",
            # +logs et +level-roles ont quitté ce lot le 2026-09-26. Le lot de
            # 2026-09-09 les avait classées « réelles, sans remplaçant
            # fonctionnel » — c'est faux des deux côtés : main les supprime au
            # boot via COMMANDS_REPLACED_BY_SETUP, et +logs se décrit elle-même
            # comme « l'ancienne interface interne ; utilisez +logsetup ». Ce
            # test ne lit que des ensembles, il ne pouvait pas voir qu'elles
            # n'existaient pas au runtime.
            "logevent", "logsearch",
            "server-audit", "server-health", "server-growth", "server-managed",
            "economy", "rob", "buy", "sell", "gamble", "deposit", "withdraw",
            "give-money", "reset-economy", "shoppanel", "shoprole", "shop", "weekly",
            "set-bio", "rep", "reputation", "repleaderboard", "rephistory",
            "voice-time",
            "addemoji", "deleteemoji", "emoji-list",
            # Second lot, 2026-09-26 : 37 commandes publiques selon
            # main.PUBLIC_COMMANDS, chargées et fonctionnelles, mais masquées et
            # classées nulle part. +poll, +remind, +translate, +invites et
            # +leaderboard-levels marchaient sans qu'on puisse les découvrir.
            "ai", "botinfo", "changelog", "channelinfo", "choose",
            "code", "correct", "event-join", "event-leave", "event-list",
            "explain", "fact-check", "feedback", "image-prompt", "improve",
            "info", "invite-leaderboard", "invited-by", "invites", "leaderboard-levels",
            "membercount", "music", "permissions", "poll", "remind",
            "reminder-cancel", "reminder-list", "report-bug", "roll", "sentrixpro",
            "serverinfo", "suggest", "summarize", "tournament-join", "tournament-list",
            "translate", "weather",
        }
        missing = expected - HELP_VISIBLE_EXTRA_COMMANDS
        self.assertEqual(missing, set(), f"toujours absentes : {missing}")

    def test_aucune_de_ces_commandes_n_est_promue_commande_directe(self):
        """Ce lot reste hors des listes « directes ».

        Le nom précédent — « ne consomme pas le budget slash » — était faux, et
        la mesure du 2026-09-26 l'a montré : démasquer une commande suffit à ce
        que la couche de surface l'expose aussi en slash. Les racines sont
        passées de 69 à 71 et les feuilles de 262 à 295. Ce que ce test garde
        réellement, c'est l'absence de chevauchement entre les listes.
        +stats a quitté ce lot : c'est désormais la surface profil canonique et une
        commande directe, donc elle est testée avec NORMAL_DIRECT_COMMANDS ailleurs."""
        overlap = HELP_VISIBLE_EXTRA_COMMANDS & NORMAL_DIRECT_COMMANDS
        self.assertEqual(overlap, set())

    def test_aucun_chevauchement_avec_admin_direct_commands(self):
        """Un nom ne doit apparaître que dans un seul ensemble de visibilité (même
        contrat que tests/test_access_matrix.py::ParityTests pour les permissions)."""
        overlap = HELP_VISIBLE_EXTRA_COMMANDS & ADMIN_DIRECT_COMMANDS
        self.assertEqual(overlap, set())

    def test_aucune_commande_annoncee_n_est_supprimee_au_boot(self):
        """L'invariant qui manquait : annoncer et supprimer se contredisent.

        integrity_hardening.safe_prune retire main.PRUNED_COMMANDS pendant
        setup_hook. Une commande présente à la fois ici et là serait promise à
        l'utilisateur puis effacée avant qu'il puisse s'en servir —
        exactement le cas de +logs et +level-roles jusqu'au 2026-09-26.

        command_catalog_cleanup vide bien COMMANDS_REPLACED_BY_SETUP pour que
        « les anciennes + restent utilisables », mais il le fait APRÈS le
        pruning : la liste source est donc la seule qui compte ici.
        """
        import main

        supprimees = set(main.COMMANDS_REPLACED_BY_SETUP) | set(main.EXACT_DUPLICATE_COMMANDS)
        for ensemble, nom in (
            (HELP_VISIBLE_EXTRA_COMMANDS, "HELP_VISIBLE_EXTRA_COMMANDS"),
            (NORMAL_DIRECT_COMMANDS, "NORMAL_DIRECT_COMMANDS"),
            (ADMIN_DIRECT_COMMANDS, "ADMIN_DIRECT_COMMANDS"),
        ):
            conflit = sorted(set(ensemble) & supprimees)
            self.assertEqual(
                conflit, [],
                f"{nom} annonce des commandes que le démarrage supprime : {conflit}")


if __name__ == "__main__":
    unittest.main()
