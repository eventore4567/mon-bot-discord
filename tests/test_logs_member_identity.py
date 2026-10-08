"""Contrats d'identité des journaux canoniques SentriX."""
from types import SimpleNamespace

from cogs.logs import Logs
from utils import log_service


def _identity(display_name: str):
    return SimpleNamespace(
        id=123456789012345678,
        name="nom-de-compte",
        display_name=display_name,
        display_avatar=None,
    )


def test_carte_log_affiche_pseudo_mention_et_identifiant():
    panel = Logs._embed("Membre parti", identity=_identity("Membre Test"))
    description = panel.description or ""
    assert "**Membre Test**" in description
    assert "<@123456789012345678>" in description
    assert "ID : `123456789012345678`" in description


def test_pseudo_mal_formate_ne_casse_pas_la_carte():
    panel = Logs._embed("Membre arrivé", identity=_identity("**faux titre**"))
    description = panel.description or ""
    assert r"\*\*faux titre\*\*" in description
    assert "<@123456789012345678>" in description


def test_journaux_ne_pinguent_pas_la_mention_affichee():
    assert log_service.LOG_ALLOWED_MENTIONS.users is False
    assert log_service.LOG_ALLOWED_MENTIONS.everyone is False
    assert log_service.LOG_ALLOWED_MENTIONS.roles is False


def test_logs_ne_coupent_pas_un_emoji_anime_dans_le_contenu():
    from cogs.logs import _short

    animated = "<a:sentrix_loading:410000000000000004>"
    # La limite arrive au milieu du marqueur animé.
    value = f"Avant {animated} après beaucoup de texte"
    preview = _short(value, 22)
    assert preview == "Avant…"
    assert len(preview) <= 22
    assert "<a:sentrix_loading:" not in preview


def test_logs_conservent_un_emoji_entier_s_il_tient():
    from cogs.logs import _short

    regular = "<:sentrix_ban:410000000000000003>"
    animated = "<a:sentrix_loading:410000000000000004>"
    for markup in (regular, animated):
        value = f"Info {markup} et un très long message"
        preview = _short(value, len("Info ") + len(markup) + 2)
        assert markup in preview
        assert len(preview) <= len("Info ") + len(markup) + 2
        assert preview.endswith("…")


def test_log_embed_conserve_les_marqueurs_dans_ses_champs():
    from cogs.logs import _short
    from utils import embeds

    animated = "<a:sentrix_loading:410000000000000004>"
    text = f"Message {animated} plus de texte"
    content = _short(text, len("Message ") + len(animated) + 3)
    panel = embeds.canonical_log_embed(
        "Message modifié",
        fields=(("Contenu", content, False),),
    )
    assert animated in panel.fields[0].value
