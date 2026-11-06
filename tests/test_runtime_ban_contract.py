"""La surface runtime du bot ne doit pas garder un ancien paramètre /ban."""
from cogs.runtime_quality_v25 import _CRITICAL_CONTRACTS
from tools.v25_quality_gate import CRITICAL_CONTRACTS


def test_runtime_contract_matches_live_ban_signature():
    expected = ("membre", "raison", "envoyer_mp", "supprimer_messages")
    assert _CRITICAL_CONTRACTS["ban"] == expected
    assert CRITICAL_CONTRACTS["ban"] == expected


def test_generated_slash_keeps_the_four_native_message_choices():
    from types import SimpleNamespace
    from discord import app_commands
    from cogs.moderation import Moderation
    import sentrix_v95_runtime as v95
    from utils.slash_catalog import _english_options

    callback,native=v95._make_callback(SimpleNamespace(),Moderation.ban)
    assert native
    slash=app_commands.Command(name='ban',description='Bannir un membre',callback=callback)
    _english_options(slash,'ban')
    options={parameter.name:parameter for parameter in slash.parameters}
    purge=options['supprimer_messages']
    assert not purge.required
    assert purge.default=='Conserver'
    assert [choice.value for choice in purge.choices]==['Conserver','15 minutes','1 heure','24 heures']
