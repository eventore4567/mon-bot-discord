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
        assert asyncio.run(cog.examiner(_Guild())) == sb.ISSUE_PREMIER_PASSAGE_SAIN
        assert cartes == []
        # Mais l'état est mémorisé : une dégradation future sera publiée.
        assert cog.bot.db.valeurs
    finally:
        _restaurer()


def test_un_constat_declenche_une_carte():
    try:
        cog, cartes = _cog([_constat()])
        assert asyncio.run(cog.examiner(_Guild())) == sb.ISSUE_PUBLIE
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
        assert asyncio.run(cog2.examiner(guild)) == sb.ISSUE_PUBLIE
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
        assert asyncio.run(cog2.examiner(guild)) == sb.ISSUE_PUBLIE
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
        assert asyncio.run(cog.examiner(guild)) == sb.ISSUE_SANS_SALON
        assert cartes, "la carte a bien été proposée au transport"
        assert db.valeurs == {}, "rien ne doit être mémorisé si rien n'est parti"

        cog2, cartes2 = _cog([_constat()], db=db, envoi=True)
        cog2.bot.db = db
        assert asyncio.run(cog2.examiner(guild)) == sb.ISSUE_PUBLIE
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
        assert asyncio.run(cog.examiner(guild)) == sb.ISSUE_HORS_CACHE
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


def test_un_passage_muet_laisse_quand_meme_une_trace():
    """Sans cette ligne, « rien publié » et « la boucle n'a jamais démarré »
    s'écrivent pareil dans les journaux : exactement le doute qu'on ne peut
    pas lever après coup. Constaté le 23/10/2026 sur le premier déploiement.
    """
    import logging

    cog, _ = _cog([])
    cog.bot.guilds = [_Guild(guild_id=i) for i in range(3)]
    journal = []

    class _Capture(logging.Handler):
        def emit(self, record):
            journal.append(record.getMessage())

    handler = _Capture()
    niveau = sb.logger.level
    sb.logger.addHandler(handler)
    sb.logger.setLevel(logging.INFO)
    try:
        asyncio.run(sb.SecurityBulletin.passage.coro(cog))
    finally:
        sb.logger.removeHandler(handler)
        sb.logger.setLevel(niveau)
        _restaurer()

    resume = next((l for l in journal if "examiné(s)" in l), None)
    assert resume, "un passage sans publication doit tout de même se journaliser"
    assert "3 serveur(s) examiné(s)" in resume
    assert sb.ISSUE_PREMIER_PASSAGE_SAIN in resume


def test_le_passage_compte_chaque_issue_separement():
    import logging

    cog, _ = _cog([])
    cog.bot.guilds = [_Guild(guild_id=1), _Guild(guild_id=2)]
    issues = []

    async def _examiner(guild, **_):
        resultat = sb.ISSUE_PUBLIE if guild.id == 1 else sb.ISSUE_SANS_SALON
        issues.append(resultat)
        return resultat

    cog.examiner = _examiner
    journal = []

    class _Capture(logging.Handler):
        def emit(self, record):
            journal.append(record.getMessage())

    handler = _Capture()
    niveau = sb.logger.level
    sb.logger.addHandler(handler)
    sb.logger.setLevel(logging.INFO)
    try:
        asyncio.run(sb.SecurityBulletin.passage.coro(cog))
    finally:
        sb.logger.removeHandler(handler)
        sb.logger.setLevel(niveau)
        _restaurer()

    resume = next(l for l in journal if "examiné(s)" in l)
    assert "2 serveur(s)" in resume
    assert sb.ISSUE_PUBLIE in resume and sb.ISSUE_SANS_SALON in resume


def test_un_serveur_en_erreur_ne_stoppe_pas_les_autres():
    import logging

    cog, _ = _cog([])
    cog.bot.guilds = [_Guild(guild_id=1), _Guild(guild_id=2)]

    async def _examiner(guild, **_):
        if guild.id == 1:
            raise RuntimeError("Discord indisponible")
        return sb.ISSUE_PUBLIE

    cog.examiner = _examiner
    journal = []

    class _Capture(logging.Handler):
        def emit(self, record):
            journal.append(record.getMessage())

    handler = _Capture()
    niveau = sb.logger.level
    sb.logger.addHandler(handler)
    sb.logger.setLevel(logging.INFO)
    try:
        asyncio.run(sb.SecurityBulletin.passage.coro(cog))
    finally:
        sb.logger.removeHandler(handler)
        sb.logger.setLevel(niveau)
        _restaurer()

    resume = next(l for l in journal if "examiné(s)" in l)
    assert sb.ISSUE_ERREUR in resume
    assert sb.ISSUE_PUBLIE in resume, "le second serveur doit avoir été traité"


# ------------------------------------- le repli quand « Serveur » n'est pas là

def _cog_par_categorie(constats, categories_qui_acceptent, db=None):
    """Un cog dont le transport n'accepte QUE certaines catégories de journal."""
    cog = sb.SecurityBulletin.__new__(sb.SecurityBulletin)
    cog.bot = type("Bot", (), {"db": db or _Db(), "guilds": []})()
    envois = []

    async def _analyser(_guild):
        return list(constats)

    async def _send_log(_bot, _guild, log_type, _embed, **_kwargs):
        envois.append(log_type)
        return log_type in categories_qui_acceptent

    sb.security_advisory.analyser_complet = _analyser
    sb.log_service.send_log = _send_log
    return cog, envois


def test_sans_journal_serveur_le_bulletin_part_en_moderation():
    # Mesuré en production : 22 serveurs sur 36 avaient des constats et aucun
    # salon « Serveur » pour les recevoir. Un bulletin dans le journal de
    # modération vaut mieux qu'un bulletin nulle part.
    try:
        cog, envois = _cog_par_categorie([_constat()], {"moderation"})
        assert asyncio.run(cog.examiner(_Guild())) == sb.ISSUE_PUBLIE
        assert envois == ["server", "moderation"], envois
    finally:
        _restaurer()


def test_le_journal_serveur_reste_le_premier_choix():
    try:
        cog, envois = _cog_par_categorie([_constat()], {"server", "moderation"})
        assert asyncio.run(cog.examiner(_Guild())) == sb.ISSUE_PUBLIE
        assert envois == ["server"], "aucun essai inutile quand le bon journal existe"
    finally:
        _restaurer()


def test_aucun_journal_du_tout_reste_sans_salon():
    try:
        db = _Db()
        cog, envois = _cog_par_categorie([_constat()], set(), db=db)
        assert asyncio.run(cog.examiner(_Guild())) == sb.ISSUE_SANS_SALON
        assert envois == list(sb.CATEGORIES_DE_REPLI), "toutes les pistes doivent être tentées"
        assert db.valeurs == {}, "rien de mémorisé : le bulletin reste dû"
    finally:
        _restaurer()


def test_le_premier_choix_est_bien_le_journal_serveur():
    assert sb.CATEGORIES_DE_REPLI[0] == "server"
    assert "moderation" in sb.CATEGORIES_DE_REPLI
