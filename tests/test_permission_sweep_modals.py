"""La CI de permissions doit reconnaître les réponses Modal Discord (type 9)."""
from tools.permission_audit_sweep import _opened_valid_modal


def _modal_call(kind=9, *, title="Créer un sondage", custom_id="poll:create"):
    return (
        "POST",
        "/interactions/123456789012345678/fake-token/callback",
        {"type": kind, "data": {"title": title, "custom_id": custom_id, "components": []}},
    )


def test_modal_valide_compte_comme_reponse_de_slash():
    assert _opened_valid_modal([_modal_call()])


def test_refus_silencieux_ne_devient_pas_autorise():
    assert not _opened_valid_modal([])
    assert not _opened_valid_modal([("POST", "/interactions/123/callback", {})])


def test_modal_invalide_ou_autre_reponse_ne_passe_pas():
    assert not _opened_valid_modal([_modal_call(kind=4)])
    assert not _opened_valid_modal([_modal_call(title="")])
    assert not _opened_valid_modal([_modal_call(custom_id="")])
    method, path, data = _modal_call()
    assert not _opened_valid_modal([("GET", path, data)])
