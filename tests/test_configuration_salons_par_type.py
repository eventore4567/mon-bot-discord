"""/setup → Configurer les salons : réglage par type, tous ou ceux choisis.

Demande de Jayden (26/10) : un bouton qui configure chaque salon selon son
rôle, deviné par son nom, avec la possibilité d'en choisir un ou plusieurs
et de corriger le type deviné.
"""
import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402
import pytest  # noqa: E402

from utils import channel_profiles as cp  # noqa: E402
from tests.test_verrouillage_salons_membres import Salon, Serveur, ow  # noqa: E402


@pytest.mark.parametrize("nom,attendu", [
    ("📢・annonces-sentrix", cp.READ_ONLY),
    ("📚・guide-sentrix", cp.READ_ONLY),
    ("❔・faq", cp.READ_ONLY),
    ("🎭・rôles", cp.READ_ONLY),
    ("🎉・giveaways", cp.READ_ONLY),
    ("💎・boosters", cp.READ_ONLY),
    ("🟢・statut-sentrix", cp.READ_ONLY),
    ("🎫・ouvrir-un-ticket", cp.READ_ONLY),
    ("💬・général", cp.DISCUSSION),
    ("🙋・présentations", cp.DISCUSSION),
    ("🤖・commandes-sentrix", cp.DISCUSSION),
    ("💡・suggestions-sentrix", cp.DISCUSSION),
    ("logs-moderation", cp.STAFF),
    ("💬・discussion-staff", cp.STAFF),
    ("moderator-only", cp.STAFF),
    ("verification", cp.SKIP),
    ("stay-muted", cp.SKIP),
    ("ticket-0042", cp.SKIP),
])
def test_classement_des_salons_du_serveur_officiel(nom, attendu):
    assert cp.classify(Salon(1, nom))[0] == attendu


class _Membre(discord.Member):
    id = 77
    __hash__ = object.__hash__

    def __init__(self):
        pass


def test_un_ticket_avec_derogation_de_membre_n_est_jamais_touche():
    salon = Salon(2, "support-jean", overwrites={_Membre(): ow(view_channel=True)})
    assert cp.classify(salon)[0] == cp.SKIP


def _plan(s, **kwargs):
    return cp.plan_profiles(
        s, verified_role=s.verifie, entry_roles=[s.membre],
        protected_ids=frozenset({s.c["reglement"].id}), **kwargs,
    )


def test_lecture_seule_les_membres_lisent_le_staff_publie():
    s = Serveur()
    plan = _plan(s, only_ids=[s.c["annonces"].id])
    cibles = {target: new for ch, target, _old, new, _had in plan.operations if ch is s.c["annonces"]}
    assert cibles[s.default_role].send_messages is False
    assert cibles[s.default_role].create_public_threads is False
    assert cibles[s.me].send_messages is True
    # La visibilité n'est jamais touchée par un salon en lecture seule.
    assert all(new.view_channel == old.view_channel for _c, _t, old, new, _h in plan.operations)


def test_staff_seulement_ne_s_ouvre_jamais_aux_membres():
    s = Serveur()
    plan = _plan(s, only_ids=[s.c["audit_public"].id])
    for _ch, target, _old, new, _had in plan.operations:
        assert target is not s.verifie or new.view_channel is not True
    cibles = {t: n for _c, t, _o, n, _h in plan.operations}
    assert cibles[s.default_role].view_channel is False
    assert cibles[s.me].view_channel is True
    # Le modérateur avait déjà sa dérogation : elle reste, rien à ajouter.
    assert s.modo not in cibles
    assert s.c["audit_public"].overwrites[s.modo].view_channel is True


def test_le_reglement_n_est_jamais_touche_meme_force():
    s = Serveur()
    plan = _plan(s, forced={s.c["reglement"].id: cp.STAFF})
    assert plan.kinds[s.c["reglement"]][0] == cp.SKIP
    assert all(ch is not s.c["reglement"] for ch, *_ in plan.operations)


def test_type_force_par_l_admin():
    s = Serveur()
    plan = _plan(s, only_ids=[s.c["general"].id], forced={s.c["general"].id: cp.READ_ONLY})
    assert plan.kinds[s.c["general"]] == (cp.READ_ONLY, "choisi par vous")
    assert any(ch is s.c["general"] and t is s.default_role for ch, t, *_ in plan.operations)


def test_selection_limite_aux_salons_choisis():
    s = Serveur()
    plan = _plan(s, only_ids=[s.c["giveaways"].id])
    assert list(plan.kinds) == [s.c["giveaways"]]


def test_un_refus_de_discord_remet_tout_comme_avant():
    from cogs import verify_setup_interactive_v78 as rules

    s = Serveur()
    plan = _plan(s, only_ids=[s.c["annonces"].id, s.c["giveaways"].id])
    avant = {cle: dict(s.c[cle].overwrites) for cle in ("annonces", "giveaways")}

    async def refuse(*_a, **_k):
        raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "refus")

    s.c["giveaways"].set_permissions = refuse
    with pytest.raises(RuntimeError):
        asyncio.run(rules.apply_profile_plan(s, plan, SimpleNamespace(id=1)))
    assert s.c["annonces"].overwrites == avant["annonces"]


def test_le_bouton_de_setup_ouvre_l_apercu_sans_rien_ecrire(monkeypatch):
    from cogs import setup_experience_v74 as v74
    from cogs import verify_setup_interactive_v78 as rules

    reglement = Salon(10, "règlement")
    reglement.mention = "<#10>"
    role = SimpleNamespace(id=20, mention="@Vérifié", name="Vérifié")
    guild = SimpleNamespace(
        id=1, channels=[reglement],
        get_channel=lambda cid: reglement if cid == 10 else None,
        get_role=lambda rid: role if rid == 20 else None,
    )

    async def rien(*_a):
        return None

    async def config(_gid):
        return {"verification_channel": 10, "verify_role": 20}

    async def ligne(*_a):
        return {"rules_text": "Respect", "image_url": None, "message_id": 99}

    async def langue(*_a):
        return "fr"

    monkeypatch.setattr(v74.language_runtime, "get_language", langue)
    monkeypatch.setattr(v74.v73, "poser_banniere", lambda _c: None)
    monkeypatch.setattr(v74.v73, "_thumbnail", lambda _b: discord.ui.Thumbnail("https://example.com/a.png"))
    ajoutes = []
    vue = SimpleNamespace(
        bot=SimpleNamespace(db=SimpleNamespace(execute=rien, get_guild_config=config, fetchone=ligne)),
        guild=guild, add_item=ajoutes.append, _add_navigation=lambda _c: None,
    )
    asyncio.run(v74.SentriXSetupV74._build_rules_access(vue))
    bouton = next(
        item for container in ajoutes for item in container.walk_children()
        if isinstance(item, discord.ui.Button) and item.label == "Configurer les salons"
    )
    appels = []

    async def apercu(_bot, g, interaction):
        appels.append(g)

    monkeypatch.setattr(rules, "send_profile_preview", apercu)

    class _Reponse:
        async def defer(self, **_k):
            pass

    asyncio.run(bouton.callback(SimpleNamespace(response=_Reponse())))
    assert appels == [guild]
    assert not reglement.ecritures


def test_choisir_des_salons_forcer_un_type_puis_appliquer(monkeypatch):
    from cogs import verify_setup_interactive_v78 as rules

    s = Serveur()
    contexte = {"verified_role": s.verifie, "entry_roles": [s.membre],
                "protected_ids": frozenset({s.c["reglement"].id})}
    appliques = []

    async def appliquer(guild, plan, actor):
        appliques.append(plan)
        return len({op[0].id for op in plan.operations})

    monkeypatch.setattr(rules, "apply_profile_plan", appliquer)

    class _Reponse:
        def __init__(self):
            self.cartes = []

        async def edit_message(self, *, content, embed, view, allowed_mentions):
            self.cartes.append(embed.description)

        async def defer(self, **_k):
            pass

    async def envoyer(*_a, **_k):
        return None

    async def scenario():
        vue = rules.ChannelProfileView(None, s, 42, contexte, cp.plan_profiles(s, **contexte))
        salons, type_ = [i for i in vue.children if isinstance(i, (discord.ui.ChannelSelect, discord.ui.Select))]
        reponse = _Reponse()
        inter = SimpleNamespace(response=reponse, followup=SimpleNamespace(send=envoyer),
                                user=SimpleNamespace(id=42))
        salons._values = [SimpleNamespace(id=s.c["general"].id)]
        await salons.callback(inter)
        type_._values = ["lecture"]
        await type_.callback(inter)
        assert "Lecture seule : 1" in reponse.cartes[-1]
        bouton = next(i for i in vue.children if getattr(i, "label", "") == "Appliquer")
        await bouton.callback(inter)

    asyncio.run(scenario())
    plan = appliques[0]
    assert list(plan.kinds) == [s.c["general"]]
    assert plan.kinds[s.c["general"]] == (cp.READ_ONLY, "choisi par vous")


def test_lecture_seule_stricte_l_animateur_n_ecrit_plus():
    # Retour de Jayden : « les animateurs peuvent écrire, c'est nul ».
    from tests.test_verrouillage_salons_membres import Role

    s = Serveur()
    animateur = Role(60, "🎉・Animateur", discord.Permissions(manage_messages=True, mention_everyone=True))
    direction = Role(61, "👑・Fondateur", discord.Permissions(administrator=True))
    gerant = Role(62, "Gérant", discord.Permissions(manage_guild=True))
    s.roles += [animateur, direction, gerant]
    annonces = s.c["annonces"]
    annonces.overwrites[animateur] = ow(view_channel=True, send_messages=True)
    annonces.overwrites[s.modo] = ow(view_channel=True, send_messages=True)
    annonces.overwrites[gerant] = ow(view_channel=True)
    plan = _plan(s, only_ids=[annonces.id])
    nouvelles = {t: n for _c, t, _o, n, _h in plan.operations}
    assert nouvelles[animateur].send_messages is None
    assert nouvelles[animateur].view_channel is True  # il lit toujours
    assert nouvelles[s.modo].send_messages is None
    assert nouvelles[s.default_role].send_messages is False
    assert nouvelles[gerant].send_messages is True
    assert direction not in nouvelles or nouvelles[direction].send_messages is True
    assert "seuls les administrateurs publient" in plan.preview()
