"""Une commande inconnue ne laisse RIEN dans le salon.

La règle était « le message s'efface vite ». Elle est devenue « il n'y a pas
de message » : sur un serveur qui héberge plusieurs bots, ``+play`` destiné à
un autre bot ne doit pas faire répondre SentriX.

Le silence est une garantie plus forte que l'expiration rapide, et ces tests
la vérifient à chaque couche — parce que l'ordre d'installation décide ici, et
qu'une couche historique qui se remettrait à parler annulerait la décision
prise au-dessus d'elle.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_le_rendu_final_ne_repond_pas_aux_commandes_inconnues():
    """Ce test exigeait une durée de vie courte — donc un message. La couche
    ne doit plus en produire du tout."""
    import ast

    arbre = ast.parse(_read("cogs/final_error_embed_v5.py"))
    branches = [
        n for n in ast.walk(arbre)
        if isinstance(n, ast.If) and "CommandNotFound" in ast.unparse(n.test)
    ]
    assert branches, "la couche ne reconnaît plus CommandNotFound du tout"
    bavardes = [
        ast.unparse(b)[:70] for b in branches
        if "send" in ast.unparse(b.body)
    ]
    assert bavardes == [], f"le rendu final répond encore : {bavardes}"


def test_official_legacy_unknown_layer_delegates_without_replying():
    """Les couches historiques ne doivent plus répondre à CommandNotFound.

    sentrix_product_update est installé en dernier et possède la réponse réelle ;
    garder une réponse ici recréerait le vieux doublon +hyelp.
    """
    source = _read("cogs/error_experience_v3.py")
    debut = source.index("isinstance(base, commands.CommandNotFound)")
    fin = source.index("isinstance(base, commands.MissingRequiredArgument)")
    branche = source[debut:fin]
    assert "return" in branche
    assert "delete_after=5" not in branche
    assert '"delete_after": float(delete_after)' in source


def test_le_proprietaire_qui_gagne_ne_dit_rien():
    """sentrix_product_update est installé EN DERNIER sur bot.on_command_error :
    c'est lui qui répond réellement à une commande inconnue. Les autres
    propriétaires peuvent tous expirer correctement sans que cela change quoi
    que ce soit à l'écran si celui-ci laissait un message permanent.

    Il n'était pas couvert ici, alors que le docstring de ce fichier annonce
    « tous les propriétaires historiques ».
    """
    source = _read("sentrix_product_update.py")
    debut = source.index("async def _plain_send")
    fin = source.index("def _install_unknown_command")
    # Sur l'AST : un simple « "send" not in source » échoue sur le NOM de la
    # fonction, `_plain_send`, sans qu'aucun envoi n'ait lieu.
    import ast
    import textwrap

    arbre = ast.parse(textwrap.dedent(source[debut:fin]))
    envois = [
        ast.unparse(n) for n in ast.walk(arbre)
        if isinstance(n, ast.Call) and "send" in ast.unparse(n.func)
    ]
    assert envois == [], f"la couche gagnante répond encore : {envois}"


def test_les_couches_historiques_ne_laissent_rien():
    v16 = _read("cogs/bot_v16_commands.py")
    v5 = _read("cogs/bot_experience_v5.py")
    assert "delete_after=5" not in v16, (
        "V16 répond encore à une commande inconnue"
    )
    assert "delete_after=5" in v5


def test_final_runtime_guard_deletes_the_actual_sentrix_unknown_reply():
    source = _read("cogs/final_stability_guard.py")
    assert "class UnknownCommandExpiryGuard" in source
    assert 'content.startswith("commande introuvable")' in source
    assert "await asyncio.sleep(5)" in source
    assert "await message.delete()" in source
