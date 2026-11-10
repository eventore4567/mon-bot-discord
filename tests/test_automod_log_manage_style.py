from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.automod import (
    GRAVITE_JAUNE,
    GRAVITE_ORANGE,
    GRAVITE_ROUGE,
    _automod_message_preview,
    _style_automod_log,
    gravite_automod,
)
from utils import embeds
from utils.log_banners import get_banner


def _fields(embed):
    return [(field.name, field.value) for field in embed.fields]


def test_all_automod_logs_use_manage_title_and_main_fields():
    member = SimpleNamespace(id=123456789, mention="<@123456789>")
    source = embeds.log_entry(
        "Action AutoMod — sanction appliquée",
        cible=member,
        cible_label="Membre",
        raison="Lien non autorisé (example.com)",
        extra={
            "Salon": "<#987654321>",
            "Message": "> https://example.com/test",
            "Sanction": "Suppression du message",
            "Messages supprimés": "1",
        },
    )

    styled = _style_automod_log(source, "automod_link")
    fields = _fields(styled)
    names = [name for name, _ in fields]

    # 10/11/2026 : le titre nomme la protection ET la sanction, et la couleur dit
    # la gravité — « Protection SentriX » partout ne se repérait pas dans un salon.
    assert styled.title == "Liens externes · Suppression du message"
    assert styled.colour.value == GRAVITE_JAUNE
    assert names[:6] == [
        "Membre",
        "Protection",
        "Sanction",
        "Raison",
        "Salon",
        "Message",
    ]
    assert dict(fields)["Protection"] == "Liens externes"
    assert dict(fields)["Sanction"] == "Suppression du message"
    assert "https://example.com/test" in dict(fields)["Message"]


def test_long_automod_message_is_quoted_and_truncated_cleanly():
    preview = _automod_message_preview("x" * 5000)
    assert preview.startswith("> ")
    assert preview.endswith("…")
    assert len(preview) <= 902


def test_attachment_only_automod_message_keeps_useful_context():
    attachment = SimpleNamespace(url="https://cdn.discordapp.com/file.png")
    message = SimpleNamespace(content="", attachments=[attachment])
    preview = _automod_message_preview(message)

    assert "https://cdn.discordapp.com/file.png" in preview


def test_automod_banner_is_available_for_manage_logs():
    assert get_banner("automod").exists()
    assert get_banner("automod_link").exists()
    assert get_banner("automod_spam").exists()


def test_l_ordre_reel_des_champs_ne_perd_ni_le_message_ni_la_sanction():
    """L'ordre réel de cogs/automod._flush_incident_log : « Messages supprimés »
    AVANT « Message », et « Infractions (1h) » sans sanction. En sous-chaîne,
    « action » prenait « Infractions » pour la sanction (« Sanction : 3 ») et
    « message » prenait « Messages supprimés » : le message supprimé disparaissait."""
    from utils import wide_logs

    member = SimpleNamespace(id=123456789, mention="<@123456789>")
    source = embeds.log_entry(
        "Action AutoMod",
        cible=member,
        cible_label="Membre",
        raison="Lien non autorisé.",
        extra={
            "Salon": "<#987654321>",
            "Messages supprimés": "2",
            "Message": "> https://example.com/test",
            "Infractions (1h)": "3",
        },
    )

    fields = dict(_fields(_style_automod_log(source, "automod_link")))
    assert fields["Sanction"] == "Suppression du message"
    assert fields["Message"] == "> https://example.com/test"
    assert fields["Messages supprimés"] == "2" and fields["Infractions (1h)"] == "3"

    body = wide_logs.narrative_body(_style_automod_log(source, "automod_link"), log_type="automod_link")
    assert "> https://example.com/test" in body
    assert "Messages supprimés : **2**" in body and "Sanction : **Suppression du message**" in body
    assert "Infractions (1h) : 3" in body and body.count("https://example.com/test") == 1


# --- 10/11/2026 : les logs AutoMod doivent sauter aux yeux -------------------

def test_la_couleur_du_log_suit_la_gravite_de_la_sanction():
    assert gravite_automod("Expulsion")[0] == GRAVITE_ROUGE
    assert gravite_automod("Bannissement définitif")[0] == GRAVITE_ROUGE
    assert gravite_automod("Mute 10 min")[0] == GRAVITE_ORANGE
    assert gravite_automod("Avertissement enregistré")[0] == GRAVITE_ORANGE
    assert gravite_automod("Suppression du message")[0] == GRAVITE_JAUNE
    # La sanction prime sur la protection : même filtre, deux gravités.
    assert gravite_automod("Suppression du message", "Anti-spam")[0] == GRAVITE_JAUNE
    assert gravite_automod("Exclusion 1 h", "Anti-spam")[0] == GRAVITE_ORANGE
    # « unban » contient « ban » : ne pas le prendre pour une sanction grave.
    assert gravite_automod("Débannissement")[0] != GRAVITE_ROUGE


def test_une_attaque_sur_le_serveur_reste_rouge_sans_sanction_nommee():
    for protection in ("Protection anti-raid", "Anti-nuke", "Permissions dangereuses"):
        assert gravite_automod("", protection)[0] == GRAVITE_ROUGE
    assert gravite_automod("Surveillance renforcée", "Risk")[0] == GRAVITE_ORANGE


def test_le_titre_du_log_nomme_la_protection_et_la_sanction():
    import discord

    source = discord.Embed(title="Anti-nuke déclenché")
    source.add_field(name="Membre", value="<@1>")
    source.add_field(name="Sanction", value="Bannissement")
    styled = _style_automod_log(source, "antinuke")
    assert "Bannissement" in styled.title and styled.colour.value == GRAVITE_ROUGE

    sans_sanction = discord.Embed(title="Protection anti-raid")
    sans_sanction.add_field(name="Statut", value="Raid contenu")
    muet = _style_automod_log(sans_sanction, "antiraid")
    assert muet.colour.value == GRAVITE_ROUGE and "·" not in muet.title
