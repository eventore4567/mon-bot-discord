"""Le bulletin ne doit parler que quand la situation change.

Un bulletin identique republié à chaque redémarrage se fait ignorer en trois
jours — et c'est le jour où il change qu'il faut le lire.
"""
import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import security_bulletin as sb  # noqa: E402
from utils import security_advisory as sa  # noqa: E402


class _Db:
    def __init__(self):
        self.valeurs = {}

    async def get_setting(self, key, default=None):
        return self.valeurs.get(key, default)

    async def set_setting(self, key, value):
        self.valeurs[key] = value


class _Guild:
    def __init__(self, guild_id=1, nom="Serveur test"):
        self.id = guild_id
        self.name = nom
        self.me = object()


def _cog(constats, *, db=None, envoi=True):
    """Un cog dont l'analyse et l'envoi sont remplacés, sans démarrer la boucle."""
    cog = sb.SecurityBulletin.__new__(sb.SecurityBulletin)
    cog.bot = type("Bot", (), {"db": db or _Db(), "guilds": []})()
    cartes = []

    async def _analyser(_guild):
        return list(constats)

    async def _send_log(_bot, guild, log_type, embed, **kwargs):
        cartes.append((log_type, embed, kwargs.get("event_key")))
        return envoi

    sb.security_advisory.analyser_complet = _analyser
    sb.log_service.send_log = _send_log
    return cog, cartes


_ORIGINE = (sa.analyser_complet, sb.log_service.send_log)


def _restaurer():
    sb.security_advisory.analyser_complet, sb.log_service.send_log = _ORIGINE


def _constat(mesure=2):
    return sa.Constat(
        "administrateurs", sa.ELEVE, "Membres administrateurs",
        f"{mesure} membres", "conséquence", "correction", mesure=mesure,
    )


def test_un_premier_passage_sain_ne_publie_rien():
    # Personne n'a demandé une carte « rien à signaler » au démarrage.
    try:
        cog, cartes = _cog([])
        assert asyncio.run(cog.examiner(_Guild())) is False
        assert cartes == []
        # Mais l'état est mémorisé : une dégradation future sera publiée.
        assert cog.bot.db.valeurs
    finally:
        _restaurer()


def test_un_constat_declenche_une_carte():
    try:
        cog, cartes = _cog([_constat()])
        assert asyncio.run(cog.examiner(_Guild())) is True
        assert len(cartes) == 1
        log_type, embed, _ = cartes[0]
        assert log_type == "server"
        assert "critique" not in (embed.title or "").casefold()
        assert "élevé" in (embed.title or "").casefold()
    finally:
        _restaurer()


def test_une_situation_inchangee_ne_republie_pas():
    try:
        cog, cartes = _cog([_constat()])
        guild = _Guild()
        asyncio.run(cog.examiner(guild))
        asyncio.run(cog.examiner(guild))
        asyncio.run(cog.examiner(guild))
        assert len(cartes) == 1, "le même bulletin ne doit partir qu'une fois"
    finally:
        _restaurer()


def test_une_degradation_republie():
    try:
        db = _Db()
        cog, cartes = _cog([_constat(mesure=2)], db=db)
        guild = _Guild()
        asyncio.run(cog.examiner(guild))

        cog2, cartes2 = _cog([_constat(mesure=5)], db=db)
        cog2.bot.db = db
        assert asyncio.run(cog2.examiner(guild)) is True
        assert len(cartes2) == 1
    finally:
        _restaurer()


def test_un_retour_a_la_normale_est_annonce():
    # Après un bulletin alarmant, savoir que c'est réglé a de la valeur.
    try:
        db = _Db()
        cog, _ = _cog([_constat()], db=db)
        guild = _Guild()
        asyncio.run(cog.examiner(guild))

        cog2, cartes2 = _cog([], db=db)
        cog2.bot.db = db
        assert asyncio.run(cog2.examiner(guild)) is True
        assert "rien à signaler" in (cartes2[0][1].title or "")
    finally:
        _restaurer()


def test_un_envoi_rate_ne_consomme_pas_le_bulletin():
    # Un serveur sans salon de journaux ne doit pas perdre son bulletin : il
    # doit le recevoir le jour où il branche ses logs.
    try:
        db = _Db()
        cog, cartes = _cog([_constat()], db=db, envoi=False)
        guild = _Guild()
        assert asyncio.run(cog.examiner(guild)) is False
        assert cartes, "la carte a bien été proposée au transport"
        assert db.valeurs == {}, "rien ne doit être mémorisé si rien n'est parti"

        cog2, cartes2 = _cog([_constat()], db=db, envoi=True)
        cog2.bot.db = db
        assert asyncio.run(cog2.examiner(guild)) is True
    finally:
        _restaurer()


def test_forcer_republie_meme_sans_changement():
    try:
        cog, cartes = _cog([_constat()])
        guild = _Guild()
        asyncio.run(cog.examiner(guild))
        asyncio.run(cog.examiner(guild, forcer=True))
        assert len(cartes) == 2
    finally:
        _restaurer()


def test_deux_serveurs_ne_partagent_pas_leur_empreinte():
    try:
        db = _Db()
        cog, cartes = _cog([_constat()], db=db)
        asyncio.run(cog.examiner(_Guild(guild_id=1)))
        asyncio.run(cog.examiner(_Guild(guild_id=2)))
        assert len(cartes) == 2
        assert len(db.valeurs) == 2
    finally:
        _restaurer()


def test_un_serveur_hors_cache_est_ignore_sans_erreur():
    try:
        cog, cartes = _cog([_constat()])
        guild = _Guild()
        guild.me = None
        assert asyncio.run(cog.examiner(guild)) is False
        assert cartes == []
    finally:
        _restaurer()


def test_la_carte_tient_dans_les_limites_de_discord():
    try:
        nombreux = [
            sa.Constat(
                f"c{i}", sa.MOYEN, f"Titre {i}",
                "constat " * 60, "conséquence " * 60, "correction " * 60, mesure=i,
            )
            for i in range(12)
        ]
        cog, cartes = _cog(nombreux)
        asyncio.run(cog.examiner(_Guild()))
        embed = cartes[0][1]

        assert len(embed) <= 6000, "Discord refuserait l'embed entier"
        assert len(embed.fields) <= 25
        for field in embed.fields:
            assert len(field.name) <= 256 and len(field.value) <= 1024
    finally:
        _restaurer()


def test_le_module_ne_declare_aucune_commande_ni_ecouteur():
    # La demande était explicite : pas de commande de plus. Et pas d'écouteur,
    # pour ne pas peser sur le budget mesuré par les gates de hiérarchie.
    assert not getattr(sb.SecurityBulletin, "__cog_commands__", ())
    assert not getattr(sb.SecurityBulletin, "__cog_listeners__", ())
    assert isinstance(sb.SecurityBulletin.passage, discord.ext.tasks.Loop)
