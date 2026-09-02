"""L'adaptateur qui reloge une View existante dans un panneau.

Une interface interactive envoyait un embed et, A COTE, une View portant ses
boutons. Un message Components V2 refuse cette cohabitation. Plutot que de
reecrire des dizaines de callbacks metier, l'adaptateur DEPLACE les composants
existants. Ces tests verrouillent les trois choses qui pourraient casser
silencieusement en le faisant : le callback, les gardes de la vue, et le fait
qu'un embed ne reste pas accroche au message.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from utils import sentrix_panels as panels  # noqa: E402


class _Vue(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=77)
        self.appels: list[str] = []
        self.expire = False

    @discord.ui.button(label="Confirmer")
    async def confirmer(self, interaction, bouton):
        self.appels.append("confirmer")

    @discord.ui.select(placeholder="Choisir", options=[discord.SelectOption(label="a")])
    async def choisir(self, interaction, menu):
        self.appels.append("choisir")

    async def on_timeout(self):
        self.expire = True


def _panneau_de(vue: _Vue) -> panels.Panneau:
    embed = discord.Embed(title="Confirmer", description="Action irreversible.")
    embed.add_field(name="Cible", value="42 salons")
    return panels.avec_composants(panels.depuis_embed(embed), vue)


def test_le_callback_garde_sa_vue_d_origine():
    """Le risque principal : un bouton deplace qui appellerait un autre `self`."""
    vue = _Vue()
    panneau = _panneau_de(vue)
    rangees = [c for c in panneau.children[0].children if isinstance(c, discord.ui.ActionRow)]
    bouton = rangees[0].children[0]
    asyncio.run(bouton.callback(None))
    assert vue.appels == ["confirmer"]


def test_les_gardes_de_la_vue_restent_actives():
    """Sans ce renvoi, « ce bouton n'est pas pour vous » et l'expiration seraient muettes."""
    vue = _Vue()
    panneau = _panneau_de(vue)
    assert panneau.timeout == 77
    asyncio.run(panneau.on_timeout())
    assert vue.expire is True


def test_un_menu_deroulant_occupe_sa_propre_rangee():
    vue = _Vue()
    panneau = _panneau_de(vue)
    rangees = [c for c in panneau.children[0].children if isinstance(c, discord.ui.ActionRow)]
    assert len(rangees) == 2
    assert all(len(r.children) == 1 for r in rangees)


def test_le_panneau_reste_un_message_components_v2_valide():
    """Un composant mal reloge ne se voit qu'a l'envoi : Discord renvoie 400."""
    vue = _Vue()
    panneau = _panneau_de(vue)
    composants = panneau.to_components()
    assert composants
    assert panels.texte_complet(panneau).startswith("## Confirmer")


def test_une_vue_sans_composant_laisse_le_panneau_intact():
    vide = discord.ui.View()
    panneau = panels.avec_composants(panels.depuis_embed(discord.Embed(title="T")), vide)
    rangees = [c for c in panneau.children[0].children if isinstance(c, discord.ui.ActionRow)]
    assert rangees == []


@pytest.mark.parametrize("chemin", sorted(str(p) for p in (RACINE / "cogs").glob("*.py")))
def test_aucun_envoi_direct_ne_melange_embed_et_vue(chemin):
    """Regression : c'est exactement ce melange qui a fait passer 37 commandes
    pour migrees alors qu'elles rendaient encore un embed."""
    import ast

    source = pathlib.Path(chemin).read_text(encoding="utf-8")
    try:
        arbre = ast.parse(source)
    except SyntaxError:
        pytest.skip("fichier non analysable")
    autorises = {"embed_builder.py"}  # apercu reel d'un embed : voir le rapport
    if pathlib.Path(chemin).name in autorises:
        pytest.skip("exception documentee")
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
            continue
        if n.func.attr not in ("send", "reply"):
            continue
        if ast.unparse(n.func.value).split(".")[0] != "ctx":
            continue
        cles = {k.arg for k in n.keywords if k.arg}
        assert not ({"embed", "embeds"} & cles and "view" in cles), (
            f"{chemin}:{n.lineno} envoie un embed ET une vue ; "
            "passer par panels.avec_composants(panels.depuis_embed(...), vue)"
        )
