"""`+security-check` doit parler du SERVEUR, pas seulement du bot.

C'est le point d'entrée réellement servi : `utils/slash_catalog.py` fait
pointer `/security scan` dessus, et le relevé d'usage de production le
liste (contrairement à `+security scan`, qui n'y apparaît pas).

Le diagnostic listait les protections SentriX et les permissions de SentriX.
Les deux disent si le bot peut travailler ; aucun ne dit si le serveur est
ouvert.
"""
import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import automod as mod  # noqa: E402


class _Permissions(discord.Permissions):
    pass


class _Membre:
    def __init__(self, membre_id, *, bot=False, permissions=None):
        self.id = membre_id
        self.bot = bot
        self.display_name = f"membre-{membre_id}"
        self.guild_permissions = permissions or discord.Permissions.all()


class _Role:
    def __init__(self, nom, *, permissions=None, membres=(), position=1, managed=False):
        self.name = nom
        self.permissions = permissions or discord.Permissions.none()
        self.members = list(membres)
        self.position = position
        self.managed = managed


class _Guild:
    def __init__(self, roles, membres, moi, *, owner_id=1):
        self.id = 42
        self.name = "Serveur test"
        self.roles = roles
        self.members = membres
        self.me = moi
        self.owner_id = owner_id
        self.default_role = next((r for r in roles if r.name == "@everyone"), None)
        self.verification_level = discord.VerificationLevel.high
        self.mfa_level = discord.MFALevel.require_2fa
        self.explicit_content_filter = discord.ContentFilter.all_members

    async def webhooks(self):
        raise discord.Forbidden(_Reponse(), "pas la permission")


class _Reponse:
    status = 403
    reason = "Forbidden"


class _Ctx:
    def __init__(self, guild):
        self.guild = guild
        self.author = _Membre(1)


def _executer(guild):
    """Déclenche le vrai callback de la commande et rend l'embed produit."""
    cog = mod.AutoMod.__new__(mod.AutoMod)

    class _Db:
        async def get_automod(self, _guild_id):
            return None

    cog.bot = type("Bot", (), {"db": _Db()})()
    envoyes = []

    async def _envoyer(_cible, panneau, **_kwargs):
        envoyes.append(panneau)

    embeds_captures = []
    depuis_embed_origine = mod.panels.depuis_embed

    def _depuis_embed(embed, **kwargs):
        embeds_captures.append(embed)
        return depuis_embed_origine(embed, **kwargs)

    envoyer_origine = mod.panels.envoyer
    mod.panels.envoyer = _envoyer
    mod.panels.depuis_embed = _depuis_embed
    try:
        asyncio.run(mod.AutoMod.security_check.callback(cog, _Ctx(guild)))
    finally:
        mod.panels.envoyer = envoyer_origine
        mod.panels.depuis_embed = depuis_embed_origine
    assert embeds_captures, "la commande doit produire un panneau"
    return embeds_captures[-1]


def _guild_expose():
    moi = _Membre(999, bot=True)
    son_role = _Role("SentriX", permissions=discord.Permissions.all(), position=10, managed=True)
    moi.top_role = son_role
    everyone = _Role("@everyone", permissions=discord.Permissions(mention_everyone=True), position=0)
    staff = [_Membre(10), _Membre(11)]
    admins = _Role("Direction", permissions=discord.Permissions(administrator=True), membres=staff)
    return _Guild([everyone, son_role, admins], [moi, *staff], moi)


def _guild_saine():
    moi = _Membre(999, bot=True)
    son_role = _Role("SentriX", permissions=discord.Permissions.all(), position=10, managed=True)
    moi.top_role = son_role
    return _Guild([_Role("@everyone", position=0), son_role], [moi], moi)


def _champ(embed, nom):
    return next((f.value for f in embed.fields if f.name == nom), None)


def test_le_diagnostic_dit_ce_qui_expose_le_serveur():
    embed = _executer(_guild_expose())
    noms = [f.name for f in embed.fields]

    assert "Exposition du serveur" in noms
    assert any("Membres administrateurs" in n for n in noms)
    assert any("tout le serveur" in n or "défaut" in n for n in noms) or any(
        "Permissions ouvertes" in n for n in noms
    )


def test_les_champs_historiques_restent_la():
    # Le diagnostic existant ne doit pas être remplacé, seulement complété.
    embed = _executer(_guild_expose())
    noms = [f.name for f in embed.fields]
    assert "Protections" in noms
    assert "Permissions du bot" in noms
    assert "Test conseillé" in noms


def test_les_permissions_du_bot_ne_sont_pas_dites_deux_fois():
    # Elles ont déjà leur champ détaillé : les répéter dans le bulletin
    # ferait deux listes différentes de la même chose.
    moi = _Membre(999, bot=True, permissions=discord.Permissions(manage_messages=True))
    son_role = _Role("SentriX", permissions=discord.Permissions.all(), position=10, managed=True)
    moi.top_role = son_role
    guild = _Guild([_Role("@everyone", position=0), son_role], [moi], moi)

    embed = _executer(guild)
    noms = [f.name for f in embed.fields]
    assert not any("Permissions manquantes pour SentriX" in n for n in noms)
    assert "Manquante" in (_champ(embed, "Permissions du bot") or "")


def test_un_serveur_sain_le_dit_sans_inventer_de_note():
    embed = _executer(_guild_saine())
    exposition = _champ(embed, "Exposition du serveur") or ""
    assert "Aucune exposition" in exposition
    assert "/100" not in exposition


def test_la_carte_reste_dans_les_limites_de_discord():
    embed = _executer(_guild_expose())
    assert len(embed) <= 6000
    assert len(embed.fields) <= 25


def test_un_webhook_illisible_nannonce_pas_zero():
    # Sans « Gérer les webhooks », annoncer « 0 webhook » serait un chiffre faux
    # présenté comme rassurant : le contrôle doit disparaître, pas mentir.
    embed = _executer(_guild_expose())
    assert not any("Webhooks actifs" in f.name for f in embed.fields)
