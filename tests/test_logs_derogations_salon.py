"""Les changements de permissions d'un salon doivent laisser une trace.

Jusqu'ici `on_guild_channel_update` ne regardait que le nom, la catégorie, le
sujet et le slowmode : ouvrir un salon privé à un rôle ne produisait AUCUN log.
"""

import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord
import pytest

from cogs.logs import (
    _diff_derogations,
    _nom_derogation,
    _texte_derogations,
)


class _RoleFactice:
    """Un rôle utilisable comme clé d'overwrites (hash par identifiant)."""

    def __init__(self, role_id: int, defaut: bool = False):
        self.id = role_id
        self._defaut = defaut

    def is_default(self) -> bool:
        return self._defaut

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, autre):
        return getattr(autre, "id", None) == self.id


def test_seules_les_transitions_sont_relevees():
    role = _RoleFactice(10)
    avant = {role: discord.PermissionOverwrite(view_channel=True)}
    apres = {role: discord.PermissionOverwrite(view_channel=True, send_messages=False)}

    change = _diff_derogations(avant, apres)

    assert len(change) == 1
    cible, autorises, refuses, neutres = change[0]
    assert cible is role
    # view_channel n'a pas bougé : l'afficher noierait la seule ligne utile.
    assert autorises == []
    assert len(refuses) == 1
    assert neutres == []


def test_un_retour_au_neutre_est_signale():
    role = _RoleFactice(11)
    avant = {role: discord.PermissionOverwrite(send_messages=False)}
    apres = {role: discord.PermissionOverwrite()}

    change = _diff_derogations(avant, apres)

    assert len(change) == 1
    _, autorises, refuses, neutres = change[0]
    assert (autorises, refuses) == ([], [])
    assert len(neutres) == 1


def test_une_derogation_ajoutee_puis_retiree():
    role = _RoleFactice(12)
    ajout = _diff_derogations({}, {role: discord.PermissionOverwrite(view_channel=True)})
    retrait = _diff_derogations({role: discord.PermissionOverwrite(view_channel=True)}, {})

    assert [c[1] for c in ajout] and not ajout[0][2]
    # Le retrait complet d'une dérogation remet la permission au neutre.
    assert retrait and retrait[0][3]


def test_aucun_changement_ne_produit_rien():
    role = _RoleFactice(13)
    identique = discord.PermissionOverwrite(view_channel=True, send_messages=False)
    assert _diff_derogations({role: identique}, {role: identique}) == []


def test_everyone_est_ecrit_en_clair_jamais_mentionne():
    # Mentionner @everyone dans un log de permissions sonnerait tout le serveur.
    assert _nom_derogation(_RoleFactice(1, defaut=True)) == "@everyone"
    assert _nom_derogation(_RoleFactice(42)) == "<@&42>"


def test_une_seule_carte_pour_plusieurs_cibles():
    # Le défaut visible d'autres bots : une carte par permission modifiée.
    roles = [_RoleFactice(100 + i) for i in range(3)]
    change = _diff_derogations(
        {},
        {r: discord.PermissionOverwrite(view_channel=True) for r in roles},
    )
    texte = _texte_derogations(change)

    assert len(change) == 3
    for role in roles:
        assert f"<@&{role.id}>" in texte


def test_le_texte_tient_dans_un_champ_discord():
    # Le pire cas réaliste : beaucoup de rôles, beaucoup de permissions chacun.
    roles = [_RoleFactice(200 + i) for i in range(30)]
    lourd = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, manage_messages=True,
        attach_files=True, embed_links=True, add_reactions=True,
        read_message_history=True, mention_everyone=False, manage_webhooks=False,
    )
    texte = _texte_derogations(_diff_derogations({}, {r: lourd for r in roles}))

    assert "autre(s) cible(s)" in texte, "ce qui ne rentre pas doit être compté"
    assert len(texte) < 1024, "la carte serait refusée par Discord"


def test_une_seule_cible_enorme_est_quand_meme_nommee():
    # Même si son bloc dépasse le budget à lui seul, la cible doit être nommée :
    # une carte qui ne dit pas QUI a changé ne vaut rien.
    tout = discord.PermissionOverwrite(**{nom: True for nom, _ in discord.PermissionOverwrite()})
    texte = _texte_derogations(_diff_derogations({}, {_RoleFactice(250): tout}))
    assert "<@&250>" in texte


@pytest.mark.parametrize("etat", [True, False, None])
def test_le_libelle_francais_est_utilise(etat):
    from utils.access_matrix import permission_label

    role = _RoleFactice(300)
    change = _diff_derogations(
        {role: discord.PermissionOverwrite(view_channel=not etat if etat is not None else True)},
        {role: discord.PermissionOverwrite(view_channel=etat)},
    )
    assert change
    attendu = permission_label("view_channel")
    assert attendu in _texte_derogations(change)


# ------------------------------------------------------- la carte rendue

def _carte(titre, champs):
    from utils import embeds

    return embeds.canonical_log_embed(titre, fields=champs)


def test_la_carte_dit_ce_qui_a_change_pour_les_permissions():
    from utils.wide_logs import narrative_body

    role = _RoleFactice(777)
    change = _diff_derogations({}, {role: discord.PermissionOverwrite(view_channel=True)})
    corps = narrative_body(
        _carte(
            "Salon modifié",
            [
                ("Salon", "<#123456789012345678>", True),
                ("Permissions", _texte_derogations(change), False),
                ("Responsable", "<@987654321098765432>", True),
            ],
        ),
        log_type="channel_update",
    )

    assert "a été modifié" in corps
    assert "<@&777>" in corps, "le rôle touché doit apparaître dans le corps"
    assert "Voir les salons" in corps


def test_un_simple_renommage_dit_le_nouveau_nom():
    # compact_fields() écarte les valeurs courtes : « Salon modifié » ne disait
    # rien du tout quand seul le nom changeait.
    from utils.wide_logs import narrative_body

    corps = narrative_body(
        _carte(
            "Salon modifié",
            [("Salon", "<#123456789012345678>", True), ("Nom", "`avant` → `après`", False)],
        ),
        log_type="channel_update",
    )
    assert "après" in corps


def test_une_categorie_nest_pas_annoncee_comme_un_salon():
    from utils.wide_logs import narrative_body

    corps = narrative_body(
        _carte(
            "Catégorie modifiée",
            [("Catégorie", "<#123456789012345678>", True), ("Nom", "`a` → `b`", False)],
        ),
        log_type="channel_update",
    )
    assert "La catégorie" in corps
    assert "Le salon" not in corps
    assert "modifiée" in corps


# ------------------------------------- le listener réellement déclenché

def _cog_capturant():
    from cogs.logs import Logs

    cog = Logs(object())
    cartes = []

    async def _capture(guild, log_type, embed, **_):
        cartes.append((log_type, embed))
        return True

    async def _pas_dacteur(*_a, **_k):
        return None, None

    cog._send = _capture
    cog._audit_actor = _pas_dacteur
    return cog, cartes


class _Guild:
    id = 123456789012345678


class _Salon:
    """Le minimum que lit on_guild_channel_update."""

    id = 222222222222222222
    guild = _Guild()
    category_id = None
    topic = None
    slowmode_delay = 0

    def __init__(self, name="general", overwrites=None):
        self.name = name
        self.overwrites = overwrites or {}


def test_un_changement_de_permission_seul_produit_bien_une_carte():
    import asyncio

    # Le bug d'origine : seuls nom/catégorie/sujet/slowmode étaient comparés,
    # donc ouvrir un salon privé à un rôle ne laissait AUCUNE trace.
    cog, cartes = _cog_capturant()
    role = _RoleFactice(555)
    avant = _Salon()
    apres = _Salon(overwrites={role: discord.PermissionOverwrite(view_channel=True)})

    asyncio.run(cog.on_guild_channel_update(avant, apres))

    assert len(cartes) == 1, "un changement de permission ne doit plus être muet"
    log_type, embed = cartes[0]
    assert log_type == "channel_update"
    perms = [f.value for f in embed.fields if f.name == "Permissions"]
    assert perms and "<@&555>" in perms[0]


def test_aucune_carte_quand_rien_na_change():
    import asyncio

    cog, cartes = _cog_capturant()
    identique = {_RoleFactice(556): discord.PermissionOverwrite(view_channel=True)}
    asyncio.run(
        cog.on_guild_channel_update(_Salon(overwrites=identique), _Salon(overwrites=identique))
    )
    assert cartes == []


def test_deux_editions_de_permissions_ne_sont_pas_confondues():
    import asyncio

    # La clé d'événement sert à dédupliquer : deux changements différents sur le
    # même salon doivent produire deux clés distinctes, sinon le second est
    # silencieusement avalé.
    from utils import log_service

    cles = []
    cog, _ = _cog_capturant()

    async def _capture(guild, log_type, embed, *, event_key=None, **_):
        cles.append(event_key)
        return True

    cog._send = _capture
    role = _RoleFactice(557)
    vide = _Salon()
    asyncio.run(
        cog.on_guild_channel_update(
            vide, _Salon(overwrites={role: discord.PermissionOverwrite(view_channel=True)})
        )
    )
    asyncio.run(
        cog.on_guild_channel_update(
            vide, _Salon(overwrites={role: discord.PermissionOverwrite(send_messages=False)})
        )
    )
    assert len(cles) == 2 and cles[0] != cles[1]
    assert log_service  # le module doit rester importable par ce chemin


# ----------------------------- la rafale de synchronisation de catégorie

class _Categorie(_Salon):
    """Une catégorie : même événement, mais elle porte des salons enfants."""

    id = 444444444444444444
    type = discord.ChannelType.category

    def __init__(self, name="Support", overwrites=None, enfants=()):
        super().__init__(name=name, overwrites=overwrites)
        self.channels = list(enfants)


class _SalonSynchronise(_Salon):
    category_id = _Categorie.id
    permissions_synced = True

    def __init__(self, salon_id, overwrites=None):
        super().__init__(name=f"salon-{salon_id}", overwrites=overwrites)
        self.id = salon_id


def test_une_synchronisation_de_categorie_ne_produit_quune_carte():
    import asyncio

    import cogs.logs as mod

    mod._CATEGORIES_PERMS_RECENTES.clear()
    cog, cartes = _cog_capturant()
    role = _RoleFactice(900)
    derogation = {role: discord.PermissionOverwrite(view_channel=False)}
    enfants = [_SalonSynchronise(500 + i, derogation) for i in range(4)]

    # D'abord la catégorie, comme Discord l'envoie, puis chaque salon synchronisé.
    asyncio.run(
        cog.on_guild_channel_update(
            _Categorie(enfants=enfants), _Categorie(overwrites=derogation, enfants=enfants)
        )
    )
    for enfant in enfants:
        asyncio.run(cog.on_guild_channel_update(_SalonSynchronise(enfant.id), enfant))

    assert len(cartes) == 1, "une édition ne doit pas produire une carte par salon"
    embed = cartes[0][1]
    libelles = {f.name for f in embed.fields}
    assert "Permissions" in libelles
    propagation = [f.value for f in embed.fields if f.name == "Propagation"]
    assert propagation and "4 salon" in propagation[0]


def test_un_salon_synchronise_isolement_garde_sa_carte():
    import asyncio

    import cogs.logs as mod

    # « Synchroniser ce salon » sans toucher à la catégorie : aucune carte de
    # catégorie récente, donc l'événement ne doit PAS être avalé.
    mod._CATEGORIES_PERMS_RECENTES.clear()
    cog, cartes = _cog_capturant()
    role = _RoleFactice(901)
    enfant = _SalonSynchronise(600, {role: discord.PermissionOverwrite(view_channel=False)})

    asyncio.run(cog.on_guild_channel_update(_SalonSynchronise(600), enfant))

    assert len(cartes) == 1


def test_un_salon_non_synchronise_garde_sa_carte_pendant_la_fenetre():
    import asyncio

    import cogs.logs as mod

    mod._CATEGORIES_PERMS_RECENTES.clear()
    mod._noter_perms_de_categorie(_Guild.id, _Categorie.id)
    cog, cartes = _cog_capturant()

    class _Autonome(_SalonSynchronise):
        permissions_synced = False

    role = _RoleFactice(902)
    enfant = _Autonome(700, {role: discord.PermissionOverwrite(send_messages=False)})
    asyncio.run(cog.on_guild_channel_update(_Autonome(700), enfant))

    assert len(cartes) == 1, "un salon qui a ses propres permissions garde sa carte"


def test_une_autre_modification_nest_jamais_avalee():
    import asyncio

    import cogs.logs as mod

    # Le repli ne vaut QUE pour un changement de permissions seul : un renommage
    # simultané doit rester visible.
    mod._CATEGORIES_PERMS_RECENTES.clear()
    mod._noter_perms_de_categorie(_Guild.id, _Categorie.id)
    cog, cartes = _cog_capturant()
    role = _RoleFactice(903)
    avant = _SalonSynchronise(800)
    apres = _SalonSynchronise(800, {role: discord.PermissionOverwrite(view_channel=False)})
    apres.name = "renomme"

    asyncio.run(cog.on_guild_channel_update(avant, apres))

    assert len(cartes) == 1
    assert any(f.name == "Nom" for f in cartes[0][1].fields)


# --------------------------------------- une permission par ligne, encadrée

def test_chaque_permission_a_sa_propre_ligne_dans_un_cadre():
    from utils.access_matrix import permission_label

    # Avant : « ⬜ Envoyer des messages, Joindre des fichiers, … » sur une seule
    # ligne, et le ⬜ s'affichait comme un carré vide sur Discord.
    role = _RoleFactice(950)
    change = _diff_derogations(
        {role: discord.PermissionOverwrite(send_messages=True, attach_files=True)},
        {role: discord.PermissionOverwrite(view_channel=True, attach_files=False)},
    )
    texte = _texte_derogations(change)

    assert "⬜" not in texte
    assert texte.count("```diff") == 1 and texte.count("```") == 2
    lignes = texte.splitlines()
    assert lignes[0] == "<@&950> · 3 permissions"
    assert any(l.startswith("+ " + permission_label("view_channel")) and l.endswith("autorisée") for l in lignes)
    assert any(l.startswith("- " + permission_label("attach_files")) and l.endswith("refusée") for l in lignes)
    assert any(l.startswith("  " + permission_label("send_messages")) and l.endswith("par défaut") for l in lignes)


def test_les_etats_sont_alignes_en_colonne():
    role = _RoleFactice(951)
    change = _diff_derogations(
        {}, {role: discord.PermissionOverwrite(view_channel=True, manage_webhooks=False)}
    )
    lignes = [l for l in _texte_derogations(change).splitlines() if l[:2] in {"+ ", "- "}]
    assert len(lignes) == 2
    positions = {l.rstrip().rfind("  ") for l in lignes}
    assert len(positions) == 1, "les mots d'état doivent tomber dans la même colonne"


def test_un_cadre_nest_jamais_coupe_par_le_budget():
    roles = [_RoleFactice(960 + i) for i in range(30)]
    tout = discord.PermissionOverwrite(**{nom: True for nom, _ in discord.PermissionOverwrite()})
    texte = _texte_derogations(_diff_derogations({}, {r: tout for r in roles}))

    assert texte.count("```") % 2 == 0, "un ``` orphelin casserait la carte"
    assert "et " in texte and "autre(s)" in texte
    assert len(texte) < 1000
