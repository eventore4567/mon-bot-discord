"""La carte de confirmation d'une sanction : ne pas sonner, ne pas rester, ne pas mélanger les langues.

Trois défauts mesurés le 23/10/2026 sur une vraie carte `+kick` :

- elle notifiait le membre visé ET le modérateur qui venait d'agir ;
- elle restait dans le salon alors que le dossier numéroté vit dans les logs ;
- sur un serveur en anglais, elle sortait à moitié traduite — « Expulsion
  completed » au-dessus de « Motif », « Par », « Dossier #2 », et le bouton
  « Historique » resté français.
"""
import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import language_runtime as lr  # noqa: E402
from cogs import moderation as mod  # noqa: E402
from utils.moderation_feedback import build_sanction_confirmation  # noqa: E402


class _U:
    def __init__(self, user_id, nom):
        self.id = user_id
        self.name = nom
        self.display_name = nom
        self.mention = f"<@{user_id}>"
        self.display_avatar = None


def _carte(action="kick", reason="", case_number=2):
    return build_sanction_confirmation(
        action=action,
        target=_U(886391809939484722, "HallowsTreat"),
        actor=_U(111, "tomioka"),
        guild_id=1234567890123456789,
        reason=reason,
        case_number=case_number,
    )


def _textes(view):
    trouves = []

    def walk(item):
        contenu = getattr(item, "content", None)
        if isinstance(contenu, str):
            trouves.append(contenu)
        for enfant in list(getattr(item, "children", ()) or ()):
            walk(enfant)
        interne = getattr(item, "item", None)
        if interne is not None and interne is not item:
            walk(interne)

    walk(view)
    return "\n".join(trouves)


def _labels(view):
    trouves = []

    def walk(item):
        label = getattr(item, "label", None)
        if isinstance(label, str) and label:
            trouves.append(label)
        for enfant in list(getattr(item, "children", ()) or ()):
            walk(enfant)
        interne = getattr(item, "item", None)
        if interne is not None and interne is not item:
            walk(interne)

    walk(view)
    return trouves


# ------------------------------------------------------------------ le ping

def test_la_confirmation_part_sans_notifier_personne():
    envois = []

    async def _envoyer(_dest, _vue, **kwargs):
        envois.append(kwargs)
        return None

    class _Ctx:
        guild = type("G", (), {"id": 1})()
        author = _U(111, "tomioka")
        interaction = None

    cog = mod.Moderation.__new__(mod.Moderation)
    origine = mod.panels.envoyer
    mod.panels.envoyer = _envoyer
    try:
        asyncio.run(
            cog._confirm_sanction(_Ctx(), "kick", _U(222, "cible"), "raison", 2)
        )
    finally:
        mod.panels.envoyer = origine

    assert envois, "la confirmation doit partir"
    autorisees = envois[0].get("allowed_mentions")
    assert autorisees is not None, "sans consigne, le défaut de panels notifie les membres"
    assert autorisees.users in (False, None)
    assert autorisees.roles in (False, None)
    assert autorisees.everyone in (False, None)


def test_les_mentions_restent_cliquables():
    # Couper la notification ne doit pas transformer les mentions en texte brut :
    # cliquer sur le membre visé reste le geste le plus utile de la carte.
    texte = _textes(_carte())
    assert "<@886391809939484722>" in texte
    assert "<@111>" in texte


# ------------------------------------------------------------- le retrait

def test_la_confirmation_est_retiree_apres_coup():
    supprimes = []

    class _Message:
        async def delete(self):
            supprimes.append("message")

    class _Ctx:
        interaction = None

    asyncio.run(mod._retirer_la_confirmation(_Ctx(), _Message(), 0))
    assert supprimes == ["message"]


def test_une_reponse_slash_passe_par_l_interaction():
    supprimes = []

    class _Interaction:
        async def delete_original_response(self):
            supprimes.append("interaction")

    class _Ctx:
        interaction = _Interaction()

    # Pas de Message en retour : c'est le cas d'une réponse différée.
    asyncio.run(mod._retirer_la_confirmation(_Ctx(), None, 0))
    assert supprimes == ["interaction"]


def test_un_message_deja_disparu_ne_fait_pas_echouer():
    class _Message:
        async def delete(self):
            raise discord.NotFound(type("R", (), {"status": 404, "reason": "x"})(), "parti")

    class _Ctx:
        interaction = None

    # Le staff a pu supprimer la carte à la main : ce n'est pas une erreur.
    asyncio.run(mod._retirer_la_confirmation(_Ctx(), _Message(), 0))


def test_le_retrait_laisse_le_temps_de_lire():
    assert 10 <= mod.DELAI_RETRAIT_CONFIRMATION_SECONDES <= 60


# ------------------------------------------------------------- les langues

def test_une_carte_anglaise_ne_garde_aucun_mot_francais():
    view = lr.translate_view_in_place(_carte())
    texte = _textes(view)

    for reste in ("Motif", "Aucune raison fournie", "Dossier", "Expulsion", "Par <@"):
        assert reste not in texte, f"{reste!r} est resté français : {texte!r}"
    assert "Member kicked" in texte
    assert "Reason" in texte and "No reason given" in texte
    assert "Case #2" in texte and "By <@111>" in texte


def test_le_bouton_persistant_est_traduit_lui_aussi():
    # Un DynamicItem enveloppe son bouton dans `.item` : son propre `label` vaut
    # None, donc le parcours ne le voyait pas et « Historique » restait français
    # au milieu d'une carte anglaise.
    assert _labels(_carte()) == ["Historique"]
    assert _labels(lr.translate_view_in_place(_carte())) == ["History"]


def test_chaque_type_de_sanction_se_traduit_entierement():
    # La traduction est une substitution de sous-chaînes : la règle courte
    # ("Bannissement", "Ban") gagnait et produisait « Ban effectué ».
    attendus = {
        "ban": "Member banned",
        "tempban": "Member temporarily banned",
        "hackban": "Banned by ID",
        "kick": "Member kicked",
        "mute": "Timeout applied",
        "unmute": "Timeout removed",
        "warn": "Warning recorded",
        "unban": "Ban lifted",
        "inconnue": "Moderation action completed",
    }
    for action, attendu in attendus.items():
        texte = _textes(lr.translate_view_in_place(_carte(action=action)))
        assert attendu in texte, f"{action} → {texte.splitlines()[0]!r}"
        premiere = texte.splitlines()[0]
        for mot in ("effectué", "appliqué", "retiré", "enregistré", "levé", "Bannissement"):
            assert mot not in premiere, f"{action} laisse du français : {premiere!r}"


def test_la_traduction_ne_mord_pas_dans_les_donnees_des_membres():
    # Les ancres courtes ne doivent pas réécrire un nom de membre ou un motif.
    for intact in ("Paris", "le Partage", "Parole donnée", "Mon dossier perso"):
        assert lr.english_ui_text(intact) == intact


def test_un_serveur_francais_garde_sa_carte_francaise():
    texte = _textes(_carte())
    assert "Expulsion effectuée" in texte
    assert "Motif" in texte and "Dossier #2" in texte
