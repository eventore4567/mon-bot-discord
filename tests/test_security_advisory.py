"""Le bulletin de sécurité doit mesurer le SERVEUR, pas le bot.

`+security scan` annonçait un score sur deux critères : les permissions de
SentriX et le nombre de filtres actifs. Un serveur avec quatorze administrateurs
et six webhooks ouverts pouvait afficher 100/100.
"""
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from utils import security_advisory as sa  # noqa: E402


class _Membre:
    def __init__(self, membre_id, *, bot=False, permissions=None):
        self.id = membre_id
        self.bot = bot
        self.display_name = f"membre-{membre_id}"
        self.guild_permissions = permissions or discord.Permissions.none()


class _Role:
    def __init__(self, nom, *, permissions=None, membres=(), position=1, managed=False):
        self.name = nom
        self.permissions = permissions or discord.Permissions.none()
        self.members = list(membres)
        self.position = position
        self.managed = managed


class _Guild:
    def __init__(
        self,
        *,
        roles=(),
        membres=(),
        owner_id=1,
        moi=None,
        verification="high",
        mfa="require_2fa",
        filtre="all_members",
    ):
        self.roles = list(roles)
        self.members = list(membres)
        self.owner_id = owner_id
        self.me = moi
        self.default_role = next((r for r in self.roles if r.name == "@everyone"), None)
        self.verification_level = discord.VerificationLevel[verification]
        self.mfa_level = discord.MFALevel[mfa]
        self.explicit_content_filter = discord.ContentFilter[filtre]


def _tout_permis():
    return discord.Permissions.all()


def _bot_complet(position=50):
    """SentriX correctement placé et correctement doté : aucun constat parasite."""
    role = _Role("SentriX", permissions=_tout_permis(), position=position, managed=True)
    return _Membre(999, bot=True, permissions=_tout_permis()), role


def _guild_saine(**extra):
    moi, son_role = _bot_complet()
    moi.top_role = son_role
    everyone = _Role("@everyone", position=0)
    return _Guild(roles=[everyone, son_role], membres=[moi], moi=moi, **extra)


def test_un_serveur_sain_ne_produit_aucun_constat():
    # Une liste vide est un vrai résultat, pas un échec d'analyse.
    assert sa.analyser(_guild_saine()) == []
    assert sa.resume([]) == "Aucune exposition détectée par les contrôles SentriX."


def test_sentrix_ne_se_signale_pas_lui_meme():
    # Se compter parmi les « bots administrateurs » reviendrait à conseiller au
    # propriétaire de désarmer le bot qu'il vient d'installer.
    saine = _guild_saine()
    assert "bots_admin" not in {c.code for c in sa.analyser(saine)}


def test_les_administrateurs_humains_sont_comptes_sans_le_proprietaire():
    moi, son_role = _bot_complet()
    moi.top_role = son_role
    admin = discord.Permissions(administrator=True)
    proprietaire = _Membre(1)
    staff = [_Membre(10), _Membre(11)]
    role_admin = _Role("Direction", permissions=admin, membres=[proprietaire] + staff)
    g = _Guild(
        roles=[_Role("@everyone", position=0), role_admin, son_role],
        membres=[moi, proprietaire, *staff],
        moi=moi,
        owner_id=1,
    )
    constats = {c.code: c for c in sa.analyser(g)}

    assert "administrateurs" in constats
    # Le propriétaire a Administrateur par construction : le compter serait du bruit.
    assert constats["administrateurs"].mesure == 2
    assert constats["administrateurs"].gravite == sa.ELEVE


def test_beaucoup_dadministrateurs_devient_critique():
    moi, son_role = _bot_complet()
    moi.top_role = son_role
    membres = [_Membre(20 + i) for i in range(5)]
    role = _Role("Admin", permissions=discord.Permissions(administrator=True), membres=membres)
    g = _Guild(
        roles=[_Role("@everyone", position=0), role, son_role],
        membres=[moi, *membres],
        moi=moi,
    )
    constats = {c.code: c for c in sa.analyser(g)}
    assert constats["administrateurs"].gravite == sa.CRITIQUE


def test_un_role_de_bot_nest_pas_compte_comme_du_staff():
    # Retirer Administrateur d'un rôle géré par une intégration casse ce bot :
    # le signaler enverrait l'utilisateur vers une « correction » destructrice.
    moi, son_role = _bot_complet()
    moi.top_role = son_role
    autre_bot = _Membre(77, bot=True, permissions=discord.Permissions(administrator=True))
    role_gere = _Role(
        "MEE6",
        permissions=discord.Permissions(administrator=True),
        membres=[autre_bot],
        managed=True,
    )
    g = _Guild(
        roles=[_Role("@everyone", position=0), role_gere, son_role],
        membres=[moi, autre_bot],
        moi=moi,
    )
    codes = {c.code for c in sa.analyser(g)}
    assert "administrateurs" not in codes
    # Mais le bot administrateur, lui, reste signalé : c'est un vrai vecteur.
    assert "bots_admin" in codes


def test_everyone_avec_mention_everyone_est_signale():
    moi, son_role = _bot_complet()
    moi.top_role = son_role
    everyone = _Role("@everyone", permissions=discord.Permissions(mention_everyone=True), position=0)
    g = _Guild(roles=[everyone, son_role], membres=[moi], moi=moi)
    constats = {c.code: c for c in sa.analyser(g)}

    assert "everyone" in constats
    assert "Mentionner @everyone" in constats["everyone"].constat or "everyone" in constats["everyone"].constat.lower()
    assert constats["everyone"].gravite == sa.ELEVE


def test_everyone_avec_gerer_les_roles_est_critique():
    moi, son_role = _bot_complet()
    moi.top_role = son_role
    everyone = _Role("@everyone", permissions=discord.Permissions(manage_roles=True), position=0)
    g = _Guild(roles=[everyone, son_role], membres=[moi], moi=moi)
    constats = {c.code: c for c in sa.analyser(g)}
    assert constats["everyone"].gravite == sa.CRITIQUE


def test_le_staff_au_dessus_du_bot_est_signale():
    # Discord refuse timeout/kick/ban sur un membre qui dépasse le bot : c'est
    # exactement le trou de l'abus privilégié.
    moi, son_role = _bot_complet(position=10)
    moi.top_role = son_role
    chef = _Membre(30)
    role_haut = _Role(
        "Fondateur",
        permissions=discord.Permissions(ban_members=True),
        membres=[chef],
        position=40,
    )
    g = _Guild(
        roles=[_Role("@everyone", position=0), son_role, role_haut],
        membres=[moi, chef],
        moi=moi,
    )
    constats = {c.code: c for c in sa.analyser(g)}
    assert constats["hierarchie"].mesure == 1


def test_un_role_haut_sans_permission_sensible_nest_pas_signale():
    # Un rôle décoratif placé haut (couleur, badge) n'est pas un risque.
    moi, son_role = _bot_complet(position=10)
    moi.top_role = son_role
    deco = _Role("Nitro", membres=[_Membre(31)], position=40)
    g = _Guild(
        roles=[_Role("@everyone", position=0), son_role, deco],
        membres=[moi],
        moi=moi,
    )
    assert "hierarchie" not in {c.code for c in sa.analyser(g)}


def test_les_webhooks_sont_comptes_quand_on_les_fournit():
    g = _guild_saine()
    assert "webhooks" not in {c.code for c in sa.analyser(g)}
    assert "webhooks" not in {c.code for c in sa.analyser(g, nombre_de_webhooks=0)}

    modere = {c.code: c for c in sa.analyser(g, nombre_de_webhooks=3)}
    assert modere["webhooks"].gravite == sa.MOYEN
    eleve = {c.code: c for c in sa.analyser(g, nombre_de_webhooks=12)}
    assert eleve["webhooks"].gravite == sa.ELEVE


def test_les_reglages_discord_faibles_remontent():
    g = _guild_saine(verification="low", mfa="disabled", filtre="disabled")
    codes = {c.code for c in sa.analyser(g)}
    assert {"verification", "mfa", "filtre_medias"} <= codes


def test_les_permissions_manquantes_du_bot_sont_dites():
    moi, son_role = _bot_complet()
    moi.top_role = son_role
    moi.guild_permissions = discord.Permissions(manage_messages=True)
    g = _Guild(roles=[_Role("@everyone", position=0), son_role], membres=[moi], moi=moi)
    constats = {c.code: c for c in sa.analyser(g)}

    assert constats["permissions_bot"].mesure == len(sa.PERMISSIONS_ATTENDUES) - 1
    assert "Bannir" in constats["permissions_bot"].constat


def test_les_constats_sont_tries_du_plus_grave_au_moins_grave():
    moi, son_role = _bot_complet()
    moi.top_role = son_role
    everyone = _Role("@everyone", permissions=discord.Permissions(manage_roles=True), position=0)
    g = _Guild(
        roles=[everyone, son_role],
        membres=[moi],
        moi=moi,
        verification="low",
        filtre="disabled",
    )
    gravites = [c.gravite for c in sa.analyser(g)]
    rangs = [{"critique": 0, "eleve": 1, "moyen": 2, "info": 3}[g_] for g_ in gravites]
    assert rangs == sorted(rangs)


def test_la_gravite_dominante_est_la_pire_jamais_une_moyenne():
    # Une moyenne diluerait l'unique critique dans les constats mineurs.
    constats = [
        sa.Constat("a", sa.INFO, "t", "c", "q", "f"),
        sa.Constat("b", sa.CRITIQUE, "t", "c", "q", "f"),
        sa.Constat("c", sa.MOYEN, "t", "c", "q", "f"),
    ]
    assert sa.gravite_dominante(constats) == sa.CRITIQUE
    assert sa.gravite_dominante([]) == sa.INFO


def test_le_resume_compte_par_gravite_sans_note_inventee():
    constats = [
        sa.Constat("a", sa.CRITIQUE, "t", "c", "q", "f"),
        sa.Constat("b", sa.CRITIQUE, "t", "c", "q", "f"),
        sa.Constat("c", sa.MOYEN, "t", "c", "q", "f"),
    ]
    texte = sa.resume(constats)
    assert "2 critique" in texte and "1 moyen" in texte
    assert "/100" not in texte


def test_lempreinte_ne_bouge_que_si_la_situation_bouge():
    # Sert à ne pas republier le même bulletin à chaque redémarrage.
    a = [sa.Constat("x", sa.ELEVE, "t", "c", "q", "f", mesure=2)]
    b = [sa.Constat("x", sa.ELEVE, "t", "c", "q", "f", mesure=2)]
    c = [sa.Constat("x", sa.ELEVE, "t", "c", "q", "f", mesure=3)]
    assert sa.empreinte(a) == sa.empreinte(b)
    assert sa.empreinte(a) != sa.empreinte(c)
    assert sa.empreinte([]) == "sain"


def test_les_champs_tiennent_dans_les_limites_de_discord():
    # Discord refuse un embed dont le TOTAL dépasse 6000 caractères, même si
    # chaque champ tient dans ses 1024 : le budget global compte aussi.
    constats = [
        sa.Constat(f"c{i}", sa.MOYEN, f"Titre {i}", "constat " * 60, "suite " * 60, "faire " * 60)
        for i in range(10)
    ]
    champs = sa.champs(constats)
    detailles = [c for c in champs if c[0] != "Et ensuite"]

    assert 0 < len(detailles) <= 6
    assert sum(len(n) + len(v) for n, v, _ in detailles) <= sa.BUDGET_TOTAL
    assert champs[-1][0] == "Et ensuite"
    assert f"{len(constats) - len(detailles)} autre" in champs[-1][1]
    for nom, valeur, _ in champs:
        assert len(nom) <= 256 and len(valeur) <= 1024


def test_des_constats_courts_passent_tous_les_six():
    # Le budget ne doit pas rogner un bulletin ordinaire.
    constats = [
        sa.Constat(f"c{i}", sa.MOYEN, f"Titre {i}", "constat court", "suite", "faire")
        for i in range(8)
    ]
    champs = sa.champs(constats)
    assert len([c for c in champs if c[0] != "Et ensuite"]) == 6
    assert "2 autre" in champs[-1][1]


def test_un_seul_constat_enorme_est_quand_meme_rendu():
    gros = sa.Constat("x", sa.CRITIQUE, "Titre", "c" * 900, "q" * 900, "f" * 900)
    champs = sa.champs([gros])
    assert len(champs) == 1 and champs[0][0].endswith("Titre")


def test_chaque_constat_dit_quoi_faire():
    # Un bulletin qui alarme sans dire quoi faire ne sert à rien.
    moi, son_role = _bot_complet(position=10)
    moi.top_role = son_role
    moi.guild_permissions = discord.Permissions.none()
    everyone = _Role("@everyone", permissions=discord.Permissions(administrator=True), position=0)
    haut = _Role(
        "Chef", permissions=discord.Permissions(ban_members=True), membres=[_Membre(5)], position=90
    )
    autre_bot = _Membre(78, bot=True, permissions=discord.Permissions(administrator=True))
    g = _Guild(
        roles=[everyone, son_role, haut],
        membres=[moi, autre_bot, _Membre(5)],
        moi=moi,
        verification="none",
        mfa="disabled",
        filtre="disabled",
    )
    constats = sa.analyser(g, nombre_de_webhooks=4)

    assert len(constats) >= 7
    for constat in constats:
        assert constat.constat and constat.consequence and constat.correction
        assert constat.marqueur in sa.MARQUEURS.values()


def test_la_gravite_survit_a_la_couche_de_texte_sobre():
    """Mesuré : un émoji en tête d'un NOM de champ est retiré à l'envoi.

    Le marqueur de gravité doit donc vivre dans la valeur, sinon il disparaît
    du bulletin publié dans les journaux sans que rien ne le signale.
    """
    from utils import embeds

    constats = [sa.Constat("x", sa.CRITIQUE, "Un titre", "constat", "suite", "faire")]
    embed = embeds.canonical_log_embed("Test", fields=sa.champs(constats))
    rendu = embed.fields[0]

    assert sa.MARQUEURS[sa.CRITIQUE] in rendu.value
    assert "Critique" in rendu.value
    assert rendu.name == "Un titre"
