"""AutoMod : vue par famille dans /setup, protections jamais auto-activées."""
from cogs.setup_security_choice_v75 import _resume_familles_automod, AUTOMOD_FAMILLES


def test_automod_families_cover_the_known_protections():
    from cogs.setup_control_center import AUTOMOD
    grouped = {key for _title, keys in AUTOMOD_FAMILLES for key in keys}
    assert {key for key, _label in AUTOMOD} <= grouped


def test_automod_summary_reads_real_state_and_never_enables_modules():
    options = [
        ("antispam", "Anti-spam", "Messages rapides"),
        ("antilink", "Anti-liens", "Liens dangereux"),
        ("antiraid", "Anti-raid", "Arrivées coordonnées"),
    ]
    empty = _resume_familles_automod(set(), options)
    assert "0/1 actifs" in empty
    assert "Aucune protection n'est activée automatiquement" in empty
    active = _resume_familles_automod({"antispam", "antiraid"}, options)
    assert "Anti-spam" in active and "Anti-raid" in active
    assert "Activés : Anti-liens" not in active
    assert "Centre de sécurité" in active
