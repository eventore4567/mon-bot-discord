from utils import microcopy


def test_permissions_are_shorter():
    assert microcopy.polish_text(
        "Tu n'as pas les permissions nécessaires pour cette action."
    ) == "Permission insuffisante pour cette action."


def test_confirmation_copy_is_compact():
    assert microcopy.polish_text(
        "La confirmation a expiré. Aucune action n'a été exécutée."
    ) == "Confirmation expirée. Aucune action exécutée."
    assert microcopy.polish_button_label("Confirmer l'action") == "Confirmer"


def test_member_prompt_is_shorter():
    text = (
        "Mentionne le membre concerné **ou réponds directement à son message**, "
        "puis reformule ta demande."
    )
    assert microcopy.polish_text(text) == "Mentionne un membre ou réponds à son message."


def test_code_blocks_are_never_rewritten():
    source = "```py\nprint(  'Aucune raison fournie'  )\n```"
    assert microcopy.polish_text(source) == source


def test_unknown_free_text_keeps_meaning():
    source = "Voici une réponse normale avec une URL https://example.com et `du code`."
    assert microcopy.polish_text(source) == source
