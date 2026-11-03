"""L'IA dirige les gestes courants par les vraies commandes (03/11/2026)."""
from utils import ai_actions as a


def _ligne(question):
    action = a.local_parse(question)
    return (action.intent if action else None), (a.build_command_line(action, prefix="+") if action else None)


def test_salon_mode_lent_prefixe_et_role_pour_tous():
    assert _ligne("verrouille le salon") == ("channel.lock", "+lock")
    assert _ligne("déverrouille le salon") == ("channel.unlock", "+unlock")
    assert _ligne("mets le mode lent à 10 secondes") == ("channel.slowmode", "+slowmode 10s")
    assert _ligne("enlève le mode lent") == ("channel.slowmode", "+slowmode 0")
    assert _ligne("change le préfixe en !") == ("config.prefix", "+setprefix !")
    assert _ligne("donne le rôle <@&55> à tout le monde") == ("role.mass", "+massrole add <@&55>")
    assert _ligne("retire le rôle @Visiteur à tout le monde") == ("role.mass", "+massrole del Visiteur")


def test_role_pour_tous_demande_confirmation_et_questions_restent_des_questions():
    assert a.exige_confirmation(a.ACTIONS["role.mass"])
    assert not a.looks_action_request("comment verrouiller un salon ?")
    assert a.looks_action_request("verrouille le salon")
