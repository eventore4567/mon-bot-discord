"""La page Sécurité de /setup doit dire l'exposition réelle du serveur.

Mesuré le 23/10/2026 : 22 serveurs sur 36 n'ont AUCUN salon de journaux
configuré. La carte poussée dans les logs ne les atteint donc jamais. Cet
écran, lui, est forcément ouvert par un admin — c'est la seule voie qui marche
partout.
"""
import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import setup_experience_v74 as v74  # noqa: E402
from utils import security_advisory as sa  # noqa: E402


class _Guild:
    id = 42
    name = "Serveur test"
    me = None
    owner_id = 1
    roles = ()
    members = ()
    default_role = None
    verification_level = discord.VerificationLevel.high
    mfa_level = discord.MFALevel.require_2fa
    explicit_content_filter = discord.ContentFilter.all_members


def _construire(constats, *, analyse_casse=False):
    """Appelle le vrai _build_security et rend les composants produits."""
    vue = v74.SentriXSetupV74.__new__(v74.SentriXSetupV74)
    vue.bot = object()
    vue.guild = _Guild()
    poses = []
    vue.add_item = poses.append
    vue._add_navigation = lambda _conteneur: None

    async def _module_enabled(*_a, **_k):
        return True

    async def _analyser(_guild):
        if analyse_casse:
            raise RuntimeError("Discord indisponible")
        return list(constats)

    origines = (
        v74.core.module_enabled,
        v74._bot_permission_audit,
        v74.v73.poser_banniere,
        v74.v73._thumbnail,
        sa.analyser_complet,
    )
    v74.core.module_enabled = _module_enabled
    v74._bot_permission_audit = lambda _g: (True, [])
    v74.v73.poser_banniere = lambda _c: False
    v74.v73._thumbnail = lambda _b: discord.ui.Thumbnail("https://example.invalid/x.png")
    sa.analyser_complet = _analyser
    try:
        asyncio.run(vue._build_security())
    finally:
        (
            v74.core.module_enabled,
            v74._bot_permission_audit,
            v74.v73.poser_banniere,
            v74.v73._thumbnail,
            sa.analyser_complet,
        ) = origines
    assert poses, "la page doit produire un conteneur"
    return poses[0]


def _texte(conteneur):
    morceaux = []

    def walk(item):
        contenu = getattr(item, "content", None)
        if isinstance(contenu, str):
            morceaux.append(contenu)
        for enfant in list(getattr(item, "children", ()) or ()):
            walk(enfant)

    walk(conteneur)
    return "\n".join(morceaux)


def _composants(conteneur):
    total = 0

    def walk(item):
        nonlocal total
        for enfant in list(getattr(item, "children", ()) or ()):
            total += 1
            walk(enfant)

    walk(conteneur)
    return total


def _constat(gravite=sa.ELEVE, titre="Membres administrateurs"):
    return sa.Constat("administrateurs", gravite, titre, "4 membres", "conséquence", "correction", 4)


def test_la_page_securite_affiche_l_exposition():
    texte = _texte(_construire([_constat()]))
    assert "Exposition du serveur" in texte
    assert "Membres administrateurs" in texte
    assert sa.MARQUEURS[sa.ELEVE] in texte


def test_un_serveur_sain_le_dit_aussi():
    texte = _texte(_construire([]))
    assert "Aucune exposition" in texte


def test_la_page_renvoie_au_diagnostic_pour_le_detail():
    # La page est déjà chargée : le détail (conséquence, marche à suivre) vit
    # dans +security-check, pas ici.
    texte = _texte(_construire([_constat()]))
    assert "+security-check" in texte


def test_le_reglage_de_la_securite_reste_la():
    texte = _texte(_construire([_constat()]))
    assert "Sécurité" in texte
    assert "Permissions du bot" in texte


def test_un_bulletin_indisponible_n_empeche_pas_d_ouvrir_la_page():
    # Sans ce garde, un serveur illisible rendait le réglage de la sécurité
    # inaccessible — on casserait la configuration pour une info secondaire.
    conteneur = _construire([], analyse_casse=True)
    texte = _texte(conteneur)
    assert "Permissions du bot" in texte
    assert "Exposition du serveur" not in texte


def test_la_page_reste_loin_du_plafond_de_composants():
    # Un panneau Discord plafonne à 40 composants et l'écran avancé en frôle
    # déjà la limite : le bulletin ne doit pas en coûter plus de deux.
    sans = _composants(_construire([], analyse_casse=True))
    avec = _composants(_construire([_constat() for _ in range(8)]))
    assert avec - sans == 2, f"{avec - sans} composants ajoutés au lieu de 2"
    assert avec < 40


def test_beaucoup_de_constats_restent_lisibles():
    nombreux = [
        sa.Constat(f"c{i}", sa.MOYEN, f"Titre {i}", "constat " * 20, "q", "f", i)
        for i in range(9)
    ]
    texte = sa.texte_compact(nombreux)
    assert "autre(s) point(s)" in texte
    assert len(texte) < 4000, "un TextDisplay Discord s'arrête à 4000 caractères"
