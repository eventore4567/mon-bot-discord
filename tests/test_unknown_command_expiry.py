"""Les erreurs de commande inconnue sont temporaires.

Une faute de frappe comme +vouch ne doit pas laisser un message SentriX permanent
dans un salon. Tous les propriétaires historiques de CommandNotFound utilisent la
même durée courte afin que l'ordre d'installation ne change pas le comportement.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_final_renderer_uses_short_unknown_command_lifetime():
    source = _read("cogs/final_error_embed_v5.py")
    assert "_DUREE_COMMANDE_INTROUVABLE = 5" in source
    assert "isinstance(base, commands.CommandNotFound)" in source
    assert "_texte_prefix_send(ctx, texte, supprimer_apres=duree)" in source


def test_official_unknown_reply_expires():
    """Ce qui compte est la DURÉE, pas le transport.

    Ce test épinglait l'appel exact ``await _send_plain(ctx, text,
    delete_after=5)``. Il interdisait donc de changer l'apparence du message
    sans le casser — et c'est ce qui a changé le 29/09/2026 : une commande
    introuvable rend maintenant un panneau avec sa bannière, comme la branche
    « argument manquant » juste à côté, au lieu d'une ligne de texte nu. La
    durée, elle, n'a pas bougé, et c'est elle que ce fichier protège.
    """
    source = _read("cogs/error_experience_v3.py")
    debut = source.index("isinstance(base, commands.CommandNotFound)")
    fin = source.index("isinstance(base, commands.MissingRequiredArgument)")
    branche = source[debut:fin]
    assert "delete_after=5" in branche
    assert '"delete_after": float(delete_after)' in source


def test_le_proprietaire_qui_gagne_expire_aussi():
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
    assert "delete_after=5" in source[debut:fin]


def test_legacy_unknown_listeners_do_not_leave_permanent_messages():
    v16 = _read("cogs/bot_v16_commands.py")
    v5 = _read("cogs/bot_experience_v5.py")
    assert "delete_after=5" in v16
    assert "delete_after=5" in v5


def test_final_runtime_guard_deletes_the_actual_sentrix_unknown_reply():
    source = _read("cogs/final_stability_guard.py")
    assert "class UnknownCommandExpiryGuard" in source
    assert 'content.startswith("commande introuvable")' in source
    assert "await asyncio.sleep(5)" in source
    assert "await message.delete()" in source
