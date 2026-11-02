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
    # Tableau court (31/10/2026) : « famille · actives/total » puis les actives.
    empty = _resume_familles_automod(set(), options)
    assert "**Messages et mentions** · 0/1\n-# Aucune" in empty
    assert "Anti-spam" not in empty
    active = _resume_familles_automod({"antispam", "antiraid"}, options)
    assert "**Messages et mentions** · 1/1\n-# Anti-spam" in active
    assert "**Arrivées et raids** · 1/1\n-# Anti-raid" in active
    assert "**Liens et arnaques** · 0/1\n-# Aucune" in active
