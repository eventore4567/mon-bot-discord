"""Les journaux gardent leurs vrais champs, meme apres l'installation reelle.

Trois modules runtime (sentrix_runtime, sentrix_visual_cleanup, log_compact_final)
reassignent ENTIEREMENT embeds.log_embed/embeds.normalize_log au demarrage reel du
bot, vers une variante qui fusionne les champs marques inline dans embed.description
sous forme de texte plutot qu'un vrai Embed.add_field(). C'est exactement ce qui
rendait « Role modifie » vide en production : narrative_body()/derive_identity()
lisent embed.fields, qui n'existaient plus.

Ce script installe sentrix_runtime pour de vrai (comme au demarrage), puis verifie
que canonical_log_embed/canonical_normalize_log restent immunises. Il tourne dans
son propre processus : l'installation est globale et irreversible pour le process.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)


def main() -> int:
    from utils import embeds, sentrix_runtime, wide_logs

    sentrix_runtime.install()

    # Meme apres l'installation, log_embed (le nom SWAPPABLE) reste corrompu —
    # c'est attendu, et documente le risque pour quiconque l'appellerait par erreur.
    corrompu = embeds.log_embed(
        "Rôle modifié", fields=[("Rôle", "<@&999888777666555444>", True)]
    )
    corrompu_ok = len(corrompu.fields) == 0

    # canonical_log_embed/canonical_normalize_log, eux, doivent rester intacts.
    panneau = embeds.canonical_log_embed(
        "Rôle modifié", fields=[("Rôle", "<@&999888777666555444>", True)]
    )
    champs_ok = [(f.name, f.value) for f in panneau.fields] == [
        ("Rôle", "<@&999888777666555444>")
    ]

    reparse = embeds.canonical_normalize_log(panneau)
    reparse_ok = any(f.value == "<@&999888777666555444>" for f in reparse.fields)

    corps = wide_logs.narrative_body(panneau, log_type="role_update")
    corps_ok = "<@&999888777666555444>" in corps

    # log_entry() est le point d'entree de 23 producteurs (automod, antinuke,
    # tickets, invites, giveaways, security_tools...) : il doit rester
    # protege lui aussi, pas seulement canonical_log_embed directement.
    entree = embeds.log_entry(
        "Ticket ouvert", cible=None, extra={"Type": "Support", "Numéro": "#42"}
    )
    log_entry_ok = {(f.name, f.value) for f in entree.fields} == {
        ("Type", "Support"), ("Numéro", "#42"),
    }

    print(f"log_embed (nom swappable) toujours corrompu, comme attendu : {corrompu_ok}")
    print(f"canonical_log_embed garde ses champs                       : {champs_ok}")
    print(f"canonical_normalize_log les preserve a la re-normalisation : {reparse_ok}")
    print(f"narrative_body affiche le role modifie                     : {corps_ok}")
    print(f"log_entry (23 appelants) garde ses champs                  : {log_entry_ok}")

    if corrompu_ok and champs_ok and reparse_ok and corps_ok and log_entry_ok:
        print("\nOK : les journaux resistent a l'installation reelle du bot.")
        return 0
    print("\nECHEC : au moins une verification a echoue.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
