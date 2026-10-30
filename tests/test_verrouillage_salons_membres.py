"""Verrouillage derrière le règlement : TOUS les salons membres, jamais le staff.

Symptôme rapporté le 25/10 : l'aperçu ne proposait que #boosters alors que
des dizaines de salons (annonces, giveaways, discussions, vocaux) étaient
ouverts aux arrivants. Cause : seul @everyone comptait. Un salon masqué à
@everyone mais ouvert par le rôle reçu à l'arrivée (« Membre », rôle
automatique) était classé « déjà privé » ; et une catégorie nommée
« Bienvenue » protégeait tous ses enfants.

Les doublures calculent les permissions comme Discord (permissions de
serveur, dérogation @everyone, puis rôles) : aucun test ne fixe à la main
ce qu'un salon « montre ».
"""
import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from sentrix_verification_v96 import VerificationConfigV96  # noqa: E402
from utils.verification_access_intelligence import (  # noqa: E402
    newcomer_access, plan_access,
)

VUE = discord.Permissions(view_channel=True, connect=True, send_messages=True)


class Role:
    def __init__(self, rid, name, perms=None, *, managed=False):
        self.id, self.name, self.managed = rid, name, managed
        self.permissions = perms if perms is not None else discord.Permissions.none()
        self.mention = f"<@&{rid}>"


class Bot:
    """Le membre SentriX : clé de dérogation, comme un vrai discord.Member."""
    id, is_bot, name = 999, True, "SentriX"


class Salon:
    def __init__(self, cid, name, *, kind="text", category=None, overwrites=None, synced=False):
        self.id, self.name, self.category = cid, name, category
        self.type = discord.ChannelType[kind]
        self.overwrites = dict(overwrites or {})
        self.permissions_synced = synced
        self.ecritures = []
        self.guild = None

    def overwrites_for(self, target):
        return self.overwrites.get(target, discord.PermissionOverwrite())

    def permissions_for(self, target):
        # @everyone seul, ou le membre du bot : même ordre que Discord.
        if getattr(target, "is_bot", False):
            return SimpleNamespace(manage_channels=True, view_channel=True)
        if target is self.guild.default_role:
            value = self.guild.default_role.permissions.value
            allow, deny = self.overwrites_for(target).pair()
            perms = discord.Permissions((value & ~deny.value) | allow.value)
            if not perms.view_channel:
                return discord.Permissions.none()
            return perms
        raise AssertionError("permissions_for appelé pour un rôle inattendu")

    async def set_permissions(self, target, *, overwrite=None, reason=None):
        self.ecritures.append((target, overwrite))
        if overwrite is None:
            self.overwrites.pop(target, None)
        else:
            self.overwrites[target] = overwrite


def ow(**kwargs):
    return discord.PermissionOverwrite(**kwargs)


class Serveur:
    """Structure type : @everyone masqué, accès donné par le rôle d'arrivée."""

    def __init__(self):
        self.id = 777
        # Comme sur un vrai serveur : @everyone a « Voir » et « Se connecter »
        # au niveau du serveur, et les salons sont masqués par dérogation.
        self.default_role = Role(777, "@everyone", VUE)
        self.membre = Role(1, "✓・Membre")                 # rôle automatique d'arrivée
        self.verifie = Role(2, "Vérifié")
        self.gamer = Role(3, "🎮 Gamer")                   # rôle facultatif (Onboarding)
        self.modo = Role(4, "Modérateur", discord.Permissions(ban_members=True, kick_members=True))
        self.booster = Role(5, "Server Booster", managed=True)
        self.roles = [self.default_role, self.membre, self.verifie, self.gamer, self.modo, self.booster]
        e, m, g, mod = self.default_role, self.membre, self.verifie, self.modo
        self.me = Bot()

        self.accueil = Salon(100, "👋 Bienvenue", kind="category",
                             overwrites={e: ow(view_channel=False), m: ow(view_channel=True)})
        self.communaute = Salon(200, "💬 Communauté", kind="category",
                                overwrites={e: ow(view_channel=False), m: ow(view_channel=True)})
        self.staff_cat = Salon(300, "🛡️ Staff", kind="category",
                               overwrites={e: ow(view_channel=False), mod: ow(view_channel=True)})
        self.verif_cat = Salon(400, "Vérification", kind="category")
        self.mixte = Salon(500, "📢 Infos", kind="category",
                           overwrites={e: ow(view_channel=False), m: ow(view_channel=True)})

        c = {}
        # Règlement visible de tous (sinon personne ne peut l'accepter).
        c["reglement"] = Salon(101, "📜・règlement", category=self.accueil,
                               overwrites={e: ow(view_channel=True)})
        c["annonces"] = Salon(102, "📢・annonces", category=self.accueil,
                              overwrites=dict(self.accueil.overwrites), synced=True)
        c["giveaways"] = Salon(103, "🎉・giveaways", category=self.accueil,
                               overwrites=dict(self.accueil.overwrites), synced=True)
        c["bienvenue"] = Salon(104, "bienvenue", category=self.accueil,
                               overwrites=dict(self.accueil.overwrites), synced=True)
        c["general"] = Salon(201, "général", category=self.communaute,
                             overwrites=dict(self.communaute.overwrites), synced=True)
        c["forum"] = Salon(202, "entraide", kind="forum", category=self.communaute,
                           overwrites=dict(self.communaute.overwrites), synced=True)
        c["vocal"] = Salon(203, "Salon vocal", kind="voice", category=self.communaute,
                           overwrites=dict(self.communaute.overwrites), synced=True)
        c["gaming"] = Salon(204, "gaming", category=self.communaute,
                            overwrites={e: ow(view_channel=False), self.gamer: ow(view_channel=True)})
        c["staff"] = Salon(301, "discussion", category=self.staff_cat,
                           overwrites=dict(self.staff_cat.overwrites), synced=True)
        c["logs"] = Salon(302, "logs-moderation", category=self.staff_cat,
                          overwrites=dict(self.staff_cat.overwrites), synced=True)
        c["audit_public"] = Salon(303, "audit", overwrites={e: ow(view_channel=True), mod: ow(view_channel=True)})
        c["prive"] = Salon(304, "salon-privé", overwrites={e: ow(view_channel=False)})
        c["captcha"] = Salon(401, "captcha", category=self.verif_cat, overwrites={e: ow(view_channel=True)})
        c["aide"] = Salon(402, "aide-arrivants", category=self.verif_cat, overwrites={e: ow(view_channel=True)})
        c["news"] = Salon(501, "nouveautés", kind="news", category=self.mixte,
                          overwrites=dict(self.mixte.overwrites), synced=True)
        c["logs_mixte"] = Salon(502, "logs-serveur", category=self.mixte,
                                overwrites=dict(self.mixte.overwrites), synced=True)
        self.c = c
        self.categories = [self.accueil, self.communaute, self.staff_cat, self.verif_cat, self.mixte]
        self.channels = [*self.categories, *c.values()]
        for salon in self.channels:
            salon.guild = self
        self.members = []

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    def get_channel(self, cid):
        return next((s for s in self.channels if s.id == cid), None)


def _plan(s, **kwargs):
    return plan_access(
        s, verification_channel_id=s.c["reglement"].id, verified_role=s.verifie,
        log_ids=[s.c["logs"].id], entry_roles=[s.membre], **kwargs,
    )


def ids(channels):
    return {ch.id for ch in channels}


def test_un_salon_ouvert_par_le_role_d_arrivee_est_verrouille():
    s = Serveur()
    plan = _plan(s)
    for cle in ("annonces", "giveaways", "general", "forum", "vocal", "news"):
        assert s.c[cle] in plan.gate, cle
    assert s.membre in plan.opened_by[s.c["news"].id]


def test_sans_le_role_d_arrivee_l_ancien_calcul_les_ratait():
    # Preuve du bug : avec @everyone seul, aucun de ces salons n'est vu.
    s = Serveur()
    plan = plan_access(s, verification_channel_id=101, verified_role=s.verifie, log_ids=[302])
    assert not ids(plan.gate) & {102, 103, 201, 202, 203, 501}


def test_une_categorie_bienvenue_ne_protege_plus_ses_enfants():
    s = Serveur()
    plan = _plan(s)
    assert s.c["annonces"] in plan.gate and s.c["giveaways"] in plan.gate
    # Le salon d'accueil lui-même reste au jugement de l'admin.
    assert s.c["bienvenue"] in plan.review and s.c["bienvenue"] not in plan.gate
    assert s.c["reglement"].id in plan.protected


def test_salons_sensibles_et_prives_jamais_verrouilles_ni_ajoutables():
    s = Serveur()
    sensibles = [s.c[k] for k in ("staff", "logs", "audit_public", "prive", "logs_mixte")]
    plan = _plan(s, include_ids=[ch.id for ch in sensibles])
    assert not ids(plan.gate) & ids(sensibles)
    assert set(plan.refused) >= ids(sensibles)
    assert s.c["audit_public"] in plan.sensitive_public


def test_un_role_facultatif_n_est_jamais_elargi_aux_verifies():
    s = Serveur()
    plan = _plan(s, include_ids=[s.c["gaming"].id])
    assert s.c["gaming"] not in plan.gate
    assert s.c["gaming"] in plan.role_restricted
    assert s.c["gaming"].id in plan.refused


def test_categorie_de_verification_proposee_a_confirmer_puis_ajoutable():
    s = Serveur()
    plan = _plan(s)
    assert s.c["aide"] in plan.review and s.c["aide"] not in plan.gate
    assert s.c["captcha"] not in plan.gate
    plan = _plan(s, include_ids=[s.c["aide"].id])
    assert s.c["aide"] in plan.gate and s.c["aide"] in plan.manual_included


def test_exclusion_manuelle_retire_un_salon():
    s = Serveur()
    plan = _plan(s, exclude_ids=[s.c["giveaways"].id])
    assert s.c["giveaways"] not in plan.gate
    assert s.c["giveaways"] in plan.manual_excluded


def test_categorie_mixte_seuls_les_salons_membres_sont_touches():
    s = Serveur()
    plan = _plan(s)
    assert s.mixte not in plan.category_gates
    assert s.c["news"] in plan.mixed_synced
    assert s.c["logs_mixte"] not in plan.gate


def test_un_refus_du_role_d_arrivee_n_est_pas_pris_pour_un_acces():
    s = Serveur()
    cache = Salon(600, "salon-cache", overwrites={
        s.default_role: ow(view_channel=True), s.membre: ow(view_channel=False),
    })
    cache.guild = s
    s.channels.append(cache)
    assert newcomer_access(cache, s.default_role, [s.membre]) == (False, False)
    assert cache not in _plan(s).gate


def test_vocal_deja_interdit_a_la_connexion_reste_intact():
    s = Serveur()
    s.c["vocal"].overwrites[s.membre] = ow(view_channel=True, connect=False)
    plan = _plan(s)
    assert s.c["vocal"] not in plan.gate
    assert s.c["vocal"] in plan.voice_already_locked


def test_apercu_compact_meme_sur_un_grand_serveur():
    s = Serveur()
    for n in range(200):
        salon = Salon(10_000 + n, f"salon-{n}", category=s.communaute,
                      overwrites=dict(s.communaute.overwrites), synced=True)
        salon.guild = s
        s.channels.append(salon)
    texte = _plan(s).preview()
    assert len(texte) < 1800
    assert "+" in texte and "logs-moderation" not in texte


def _moteur(s):
    async def config(_gid):
        return {"autorole": s.membre.id}

    async def rien(*_a, **_k):
        return []

    async def aucun(*_a, **_k):
        return None

    bot = SimpleNamespace(db=SimpleNamespace(
        get_guild_config=config, fetchall=rien, fetchone=aucun, execute=aucun,
    ))
    return VerificationConfigV96(bot)


def test_le_moteur_retire_l_acces_du_role_d_arrivee_et_jamais_le_staff():
    s = Serveur()
    moteur = _moteur(s)

    async def appliquer():
        return await moteur._apply_auto_access(
            s, verification_channel=s.c["reglement"], verified_role=s.verifie,
            actor=SimpleNamespace(id=1),
        )

    asyncio.run(appliquer())
    e, m, v = s.default_role, s.membre, s.verifie
    # #gaming (rôle facultatif) rend Communauté MIXTE : la catégorie n'est pas
    # touchée, ses salons membres le sont un par un.
    assert not s.communaute.ecritures
    for cle in ("general", "forum", "vocal"):
        salon = s.c[cle]
        assert salon.overwrites[v].view_channel is True, cle
        assert salon.overwrites.get(m, ow()).view_channel is None, cle
    assert not s.c["gaming"].ecritures
    # Après verrouillage, un arrivant (@everyone + Membre) ne voit plus rien.
    for cle in ("annonces", "giveaways", "news"):
        assert newcomer_access(s.c[cle], e, [m]) == (False, False), cle
        assert newcomer_access(s.c[cle], e, [m, v])[0] is True, cle
    # Déjà privés, portail ou rôle facultatif : jamais touchés.
    for cle in ("staff", "logs", "prive", "reglement", "gaming"):
        assert not s.c[cle].ecritures, cle
    assert not s.staff_cat.ecritures and not s.mixte.ecritures
    # Staff/logs visibles des arrivants : masqués, jamais ouverts à Vérifié,
    # le bot garde l'accès pour y écrire ses logs.
    for cle in ("audit_public", "logs_mixte"):
        salon = s.c[cle]
        assert all(cible is not v for cible, _ow in salon.ecritures), cle
        assert newcomer_access(salon, e, [m]) == (False, False), cle
        assert newcomer_access(salon, e, [m, v])[0] is False, cle
        assert salon.overwrites[s.me].view_channel is True, cle
    # Le modérateur voyait #audit par sa dérogation : il la garde.
    assert s.c["audit_public"].overwrites[s.modo].view_channel is True


def test_le_vocal_membre_gere_voir_et_se_connecter():
    s = Serveur()
    s.communaute.overwrites[s.membre] = ow(view_channel=True, connect=True)
    s.c["vocal"].permissions_synced = False
    s.c["vocal"].overwrites = dict(s.communaute.overwrites)
    moteur = _moteur(s)
    asyncio.run(moteur._apply_auto_access(
        s, verification_channel=s.c["reglement"], verified_role=s.verifie,
        actor=SimpleNamespace(id=1),
    ))
    vocal, e, m, v = s.c["vocal"], s.default_role, s.membre, s.verifie
    assert vocal.overwrites[e].view_channel is False and vocal.overwrites[e].connect is False
    assert vocal.overwrites[v].view_channel is True and vocal.overwrites[v].connect is True
    assert vocal.overwrites.get(m, ow()).connect is None
    assert newcomer_access(vocal, e, [m]) == (False, False)
    assert newcomer_access(vocal, e, [m, v]) == (True, True)


def test_un_role_porte_par_presque_tous_est_mesure_comme_role_d_arrivee():
    s = Serveur()
    autre = Role(8, "Arrivant (autre bot)")
    s.roles.append(autre)
    s.members = [SimpleNamespace(bot=False, roles=[s.default_role, autre]) for _ in range(20)]
    s.members.append(SimpleNamespace(bot=False, roles=[s.default_role, autre, s.modo]))
    moteur = _moteur(s)
    roles = asyncio.run(moteur._entry_roles(s, s.verifie, None))
    assert autre in roles
    assert s.modo not in roles and s.verifie not in roles and s.booster not in roles


def test_selection_manuelle_recalcule_l_apercu_et_part_a_la_confirmation(monkeypatch):
    from cogs import verify_setup_interactive_v78 as rules

    s = Serveur()
    appels = []

    async def apercu(bot, guild, *, include_ids=(), exclude_ids=(), release_onboarding=False):
        appels.append((set(include_ids), set(exclude_ids)))
        return _plan(s, include_ids=include_ids, exclude_ids=exclude_ids), s.verifie, {}

    verrous = []

    async def verrouiller(bot, guild, actor, *, include_ids=(), exclude_ids=(), release_onboarding=False):
        verrous.append((set(include_ids), set(exclude_ids)))
        return 3, 9

    monkeypatch.setattr(rules, "preview_published_channels", apercu)
    monkeypatch.setattr(rules, "lock_published_channels", verrouiller)

    class _Reponse:
        def __init__(self):
            self.contenus = []

        async def edit_message(self, *, content, embed, view, allowed_mentions):
            assert content is None and embed.title == "Vérifier les accès"
            self.contenus.append(embed.description)

        async def defer(self, **_k):
            pass

    async def scenario():
        plan = _plan(s)
        vue = rules.RulesLockConfirmView(
            None, s, 42, rules.plan_signature(plan, role=s.verifie, state={}, guild=s), plan=plan,
        )
        selecteurs = [i for i in vue.children if isinstance(i, discord.ui.ChannelSelect)]
        assert [i.placeholder for i in selecteurs] == [
            "Retirer des salons du verrouillage", "Ajouter des salons « à confirmer »",
        ]
        retirer, ajouter = selecteurs
        retirer._values = [SimpleNamespace(id=s.c["giveaways"].id)]
        ajouter._values = [SimpleNamespace(id=s.c["aide"].id)]
        reponse = _Reponse()
        inter = SimpleNamespace(response=reponse, followup=SimpleNamespace(send=_envoi))
        await retirer.callback(inter)
        await ajouter.callback(inter)
        assert "Exclus par vous" in reponse.contenus[-1]
        assert "Ajoutés par vous" in reponse.contenus[-1]
        bouton = next(i for i in vue.children if getattr(i, "label", "") == "Confirmer le verrouillage")
        inter.user = SimpleNamespace(id=42)
        await bouton.callback(inter)

    async def _envoi(*_a, **_k):
        return None

    asyncio.run(scenario())
    assert appels[-1] == ({s.c["aide"].id}, {s.c["giveaways"].id})
    assert verrous == [({s.c["aide"].id}, {s.c["giveaways"].id})]


def test_les_salons_onboarding_sont_nommes_avec_la_marche_a_suivre():
    s = Serveur()
    plan = _plan(s, onboarding_ids=[s.c["annonces"].id], include_ids=[s.c["annonces"].id])
    assert s.c["annonces"] not in plan.gate
    assert s.c["annonces"] in plan.onboarding
    assert s.c["annonces"].id in plan.refused
    texte = plan.preview()
    assert "Onboarding Discord : 1" in texte and "annonces" in texte
    assert "Paramètres du serveur → Onboarding" in texte


def test_salons_sensibles_distingues_arrivants_et_role_verifie():
    s = Serveur()
    # Un ancien verrouillage a ouvert #discussion (staff) au rôle Vérifié.
    s.c["staff"].overwrites[s.verifie] = ow(view_channel=True)
    s.c["staff"].permissions_synced = False
    plan = _plan(s)
    texte = plan.preview()
    assert "Staff/logs à sécuriser" in texte  # #audit public : masqué automatiquement
    assert "staff/logs ouverts au rôle Vérifié" in texte
    from utils.verification_access_intelligence import decision_rows
    lignes = " | ".join(decision_rows(s, plan))
    assert "#discussion -> INCHANGE:staff/logs/sécurité !OUVERT_AU_ROLE_VERIFIE" in lignes
    assert "#audit -> INCHANGE:staff/logs/sécurité !VISIBLE_ARRIVANTS(@everyone)" in lignes


def test_relevé_dit_si_le_salon_sensible_est_vu_par_le_role_d_arrivee_seul():
    s = Serveur()
    # @everyone sans « Voir » au niveau serveur, rôle d'arrivée avec « Voir » :
    # un salon de logs SANS dérogation est vu des arrivants via ce rôle.
    s.default_role.permissions = discord.Permissions.none()
    s.membre.permissions = discord.Permissions(view_channel=True)
    logs = Salon(700, "logs-tickets")
    logs.guild = s
    s.channels.append(logs)
    plan = _plan(s)
    assert logs in plan.sensitive_public
    from utils.verification_access_intelligence import decision_rows
    lignes = " | ".join(decision_rows(s, plan))
    assert "#logs-tickets -> INCHANGE:staff/logs/sécurité !VISIBLE_ARRIVANTS(rôle d'arrivée)" in lignes


def test_un_staff_qui_ne_voyait_que_par_ses_permissions_garde_l_acces():
    # Salon de logs SANS dérogation, vu de tous via les permissions de
    # serveur : poser le refus @everyone sans autorisation explicite ferait
    # perdre l'accès au modérateur. Il reçoit donc une autorisation explicite.
    s = Serveur()
    s.modo.permissions = discord.Permissions(view_channel=True, ban_members=True)
    logs = Salon(800, "logs-tickets")
    logs.guild = s
    s.channels.append(logs)
    asyncio.run(_moteur(s)._apply_auto_access(
        s, verification_channel=s.c["reglement"], verified_role=s.verifie,
        actor=SimpleNamespace(id=1),
    ))
    e, m, v = s.default_role, s.membre, s.verifie
    assert newcomer_access(logs, e, [m]) == (False, False)
    assert newcomer_access(logs, e, [s.modo])[0] is True
    assert logs.overwrites[s.me].view_channel is True
    assert v not in logs.overwrites


class _Onboarding:
    def __init__(self, s):
        self.enabled = True
        self.mode = discord.OnboardingMode.default
        self.default_channel_ids = [s.c["annonces"].id, s.c["general"].id]
        self.default_channels = [s.c["annonces"], s.c["general"]]
        # Une VRAIE question discord.py : un Onboarding sans question a laissé
        # passer to_dict() sans son « id » obligatoire (prod, 25/10 23:39).
        # Construite comme discord.py le fait d'une réponse de l'API.
        question = discord.OnboardingPrompt.from_dict(data={
            "id": 4141, "type": 0, "title": "Tes centres d'intérêt ?",
            "single_select": False, "required": False, "in_onboarding": True,
            "options": [{
                "id": 4242, "title": "Gamer", "description": "Salons jeux",
                "channel_ids": [s.c["gaming"].id], "role_ids": [s.gamer.id],
            }],
        }, state=None, guild=s)
        self.prompts = [question]


def _serveur_onboarding(refuse_permission=False):
    s = Serveur()
    s.rules_channel = s.c["reglement"]
    s.public_updates_channel = None
    etat = {"onboarding": _Onboarding(s), "editions": []}

    async def onboarding():
        return etat["onboarding"]

    async def edit_onboarding(**kwargs):
        etat["editions"].append(kwargs)
        if kwargs.get("enabled") is False:
            etat["onboarding"].default_channel_ids = []
            etat["onboarding"].default_channels = []

    s.onboarding = onboarding
    s.edit_onboarding = edit_onboarding
    s._state = None
    if refuse_permission:
        async def refuse(*_a, **_k):
            raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "refus")
        s.c["giveaways"].set_permissions = refuse
    return s, etat


def test_onboarding_libere_puis_salons_verrouilles():
    s, etat = _serveur_onboarding()
    moteur = _moteur(s)
    sauvegardes = []

    async def execute(sql, params=()):
        if "INSERT INTO verification_onboarding_backup" in sql:
            sauvegardes.append(params)

    moteur.bot.db.execute = execute
    plan = asyncio.run(moteur._access_plan(
        s, verification_channel=s.c["reglement"], verified_role=s.verifie, release_onboarding=True,
    ))
    assert s.c["annonces"] in plan.onboarding_released and s.c["annonces"] in plan.gate
    assert "Onboarding Discord désactivé" in plan.preview()
    asyncio.run(moteur._apply_auto_access(
        s, verification_channel=s.c["reglement"], verified_role=s.verifie,
        actor=SimpleNamespace(id=1), release_onboarding=True,
    ))
    assert sauvegardes, "la sauvegarde doit précéder la modification"
    assert etat["editions"][0]["enabled"] is False
    assert newcomer_access(s.c["annonces"], s.default_role, [s.membre]) == (False, False)


def test_sans_accord_l_onboarding_n_est_jamais_touche():
    s, etat = _serveur_onboarding()
    plan = asyncio.run(_moteur(s)._access_plan(
        s, verification_channel=s.c["reglement"], verified_role=s.verifie,
    ))
    assert s.c["annonces"] in plan.onboarding and s.c["annonces"] not in plan.gate
    asyncio.run(_moteur(s)._apply_auto_access(
        s, verification_channel=s.c["reglement"], verified_role=s.verifie,
        actor=SimpleNamespace(id=1),
    ))
    assert etat["editions"] == []


def test_echec_d_ecriture_restaure_l_onboarding_et_les_permissions():
    import pytest

    s, etat = _serveur_onboarding(refuse_permission=True)
    avant = dict(s.c["annonces"].overwrites)
    with pytest.raises(RuntimeError):
        asyncio.run(_moteur(s)._apply_auto_access(
            s, verification_channel=s.c["reglement"], verified_role=s.verifie,
            actor=SimpleNamespace(id=1), release_onboarding=True,
        ))
    assert etat["editions"][0]["enabled"] is False
    assert etat["editions"][-1]["enabled"] is True
    assert [c.id for c in etat["editions"][-1]["default_channels"]] == [s.c["annonces"].id, s.c["general"].id]
    assert s.c["annonces"].overwrites == avant


def test_un_salon_candidatures_public_n_est_jamais_masque_d_office():
    s = Serveur()
    candid = Salon(900, "📝・candidatures", overwrites={s.default_role: ow(view_channel=True)})
    candid.guild = s
    s.channels.append(candid)
    plan = _plan(s)
    assert candid in plan.sensitive_public
    assert candid not in plan.secure_targets and candid not in plan.gate
    assert "à vérifier manuellement : 1" in plan.preview()
    asyncio.run(_moteur(s)._apply_auto_access(
        s, verification_channel=s.c["reglement"], verified_role=s.verifie,
        actor=SimpleNamespace(id=1),
    ))
    assert not candid.ecritures


def test_le_salon_des_mises_a_jour_communaute_est_libere_avec_l_onboarding():
    # Serveur officiel : #annonces-sentrix restait bloqué après libération,
    # gardé comme « mises à jour Communauté ». Seul le salon des règles
    # doit rester lisible par tous.
    s, _etat = _serveur_onboarding()
    s.public_updates_channel = s.c["news"]
    plan = asyncio.run(_moteur(s)._access_plan(
        s, verification_channel=s.c["reglement"], verified_role=s.verifie, release_onboarding=True,
    ))
    assert s.c["news"] in plan.gate and s.c["news"] not in plan.onboarding
    assert s.c["reglement"] not in plan.gate
    plan = asyncio.run(_moteur(s)._access_plan(
        s, verification_channel=s.c["reglement"], verified_role=s.verifie,
    ))
    assert s.c["news"] in plan.onboarding and s.c["news"] not in plan.gate


def test_la_sauvegarde_de_l_onboarding_est_restaurable_avec_ses_questions():
    import json

    s, _etat = _serveur_onboarding()
    moteur = _moteur(s)
    lignes = []

    async def execute(sql, params=()):
        if "INSERT INTO verification_onboarding_backup" in sql:
            lignes.append(params)

    moteur.bot.db.execute = execute
    asyncio.run(moteur._release_onboarding(s, "test"))
    sauvegarde = json.loads(lignes[0][1])
    question = sauvegarde["prompts"][0]
    assert question["id"] == 4141 and question["options"][0]["id"] == 4242
    assert question["options"][0]["role_ids"] == [s.gamer.id]
    relue = discord.OnboardingPrompt.from_dict(data=question, state=None, guild=s)
    assert relue.id == 4141 and relue.options[0].id == 4242


def _creation(monkeypatch, s, salon, *, auto_access=1, publie=True):
    """Simule la création d'un salon après un verrouillage confirmé."""
    import sentrix_verification_v96 as v96
    from cogs import verify_setup_interactive_v78 as rules

    monkeypatch.setattr(v96, "_CREATION_SETTLE_SECONDS", 0)

    async def etat(_bot, _guild):
        if not publie:
            return None
        return {"channel_id": s.c["reglement"].id, "role_id": s.verifie.id, "message_id": 1}

    monkeypatch.setattr(rules, "published_rules_state", etat)
    salon.guild = s
    s.channels.append(salon)
    moteur = _moteur(s)

    async def config(_gid):
        return {"autorole": s.membre.id, "verification_auto_access": auto_access}

    moteur.bot.db.get_guild_config = config
    asyncio.run(moteur.on_guild_channel_create(salon))
    return salon


def test_un_nouveau_salon_membre_est_verrouille_tout_seul(monkeypatch):
    s = Serveur()
    neuf = Salon(950, "nouveau-salon", category=s.communaute,
                 overwrites=dict(s.communaute.overwrites), synced=True)
    _creation(monkeypatch, s, neuf)
    assert newcomer_access(neuf, s.default_role, [s.membre]) == (False, False)
    assert newcomer_access(neuf, s.default_role, [s.membre, s.verifie])[0] is True
    # Rien d'autre n'est touché par cette adaptation ciblée.
    assert not s.c["general"].ecritures and not s.c["audit_public"].ecritures


def test_un_nouveau_salon_de_logs_est_masque_aux_arrivants(monkeypatch):
    s = Serveur()
    logs = Salon(951, "logs-nouveaux", overwrites={s.default_role: ow(view_channel=True)})
    _creation(monkeypatch, s, logs)
    assert newcomer_access(logs, s.default_role, [s.membre])[0] is False
    assert s.verifie not in logs.overwrites
    assert logs.overwrites[s.me].view_channel is True


def test_un_ticket_prive_n_est_jamais_touche(monkeypatch):
    s = Serveur()
    ticket = Salon(952, "ticket-0042", overwrites={s.default_role: ow(view_channel=False)})
    _creation(monkeypatch, s, ticket)
    assert not ticket.ecritures


def test_sans_verrouillage_confirme_rien_n_est_adapte(monkeypatch):
    s = Serveur()
    neuf = Salon(953, "nouveau-salon", category=s.communaute,
                 overwrites=dict(s.communaute.overwrites), synced=True)
    _creation(monkeypatch, s, neuf, auto_access=0)
    assert not neuf.ecritures
    s = Serveur()
    neuf = Salon(954, "nouveau-salon", category=s.communaute,
                 overwrites=dict(s.communaute.overwrites), synced=True)
    _creation(monkeypatch, s, neuf, publie=False)
    assert not neuf.ecritures


def test_un_salon_membre_ferme_a_tous_est_rouvert_aux_verifies():
    """Relevé du 30/10/2026 : « 0 à verrouiller, 19 inchangés » — tous les salons
    membres étaient fermés à tout le monde, vérifiés compris."""
    s = Serveur()
    ferme = Salon(700, "💬・discussions", overwrites={s.default_role: ow(view_channel=False)})
    piege = Salon(701, "honeypot", overwrites={s.default_role: ow(view_channel=False)})
    for salon in (ferme, piege):
        salon.guild = s
        s.channels.append(salon)
    plan = _plan(s)
    assert ferme in plan.gate and ferme in plan.closed_opened
    assert piege not in plan.gate and piege in plan.review
    assert "fermé(s) à tous" in plan.preview()
