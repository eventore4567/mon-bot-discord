"""Le gestionnaire d'erreur slash ne doit pas planter sur un objet à __slots__.

`discord.Interaction` déclare des __slots__ : y poser un attribut libre lève
AttributeError. final_error_embed_v5.slash_error le faisait, donc toute erreur
arrivant par l'arbre slash (option invalide, contrôle d'application refusé)
faisait planter son propre gestionnaire — l'utilisateur restait sur
« SentriX réfléchit… ». Mesuré sur /poll le 07/10/2026.
"""
import discord

from cogs import final_error_embed_v5 as v5


class _Slotted:
    __slots__ = ("id",)

    def __init__(self, ident):
        self.id = ident


def test_la_vraie_interaction_refuse_un_attribut_libre():
    """Le constat qui justifie le registre : si discord.py changeait, ce test le dirait."""
    assert "_sentrix_error_finalized" not in getattr(discord.Interaction, "__slots__", ())


def test_marquer_une_interaction_a_slots_ne_plante_pas_et_se_retient():
    objet = _Slotted(987654321)
    assert not v5._deja_finalisee(objet)
    v5._marquer_finalisee(objet)          # ne doit pas lever
    assert v5._deja_finalisee(objet)


def test_un_contexte_ordinaire_garde_son_attribut():
    class Ctx:
        id = 1
    ctx = Ctx()
    v5._marquer_finalisee(ctx)
    assert ctx._sentrix_error_finalized is True and v5._deja_finalisee(ctx)


def test_le_registre_reste_borne():
    for i in range(v5._FINALIZED_MAX + 50):
        v5._marquer_finalisee(_Slotted(10**12 + i))
    assert len(v5._FINALIZED_IDS) <= v5._FINALIZED_MAX
