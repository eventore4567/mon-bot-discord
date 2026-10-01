from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_command_errors_use_plain_text_not_embeds():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    start = source.index("    async def on_command_error")
    end = source.index("    async def on_app_command_error", start)
    block = source[start:end]

    assert "ctx.send(embed=" not in block
    assert 'ctx.send("Une erreur est survenue. Merci de réessayer.")' in block
    assert "Permission(s) manquante(s) : `" in block
    assert "Il manque `" in block


def test_slash_errors_use_plain_text_not_embeds():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    start = source.index("    async def on_app_command_error")
    end = source.index("\n\n\nasync def main():", start)
    block = source[start:end]

    assert "embed =" not in block
    assert "send_message(message, ephemeral=True)" in block
    assert "followup.send(message, ephemeral=True)" in block
    assert 'message = "Une erreur est survenue. Merci de réessayer."' in block


def test_runtime_prefix_error_layer_stays_plain_text():
    source = (ROOT / "cogs" / "error_experience_v3.py").read_text(encoding="utf-8")
    start = source.index("async def _handle_user_error")
    end = source.index("\n\ndef install(", start)
    block = source[start:end]

    assert "panels.envoyer(" not in block
    assert "embeds.error(" not in block
    assert "embeds.warning(" not in block
    assert "_send_plain(" in block


def test_runtime_slash_error_layer_stays_plain_text():
    source = (ROOT / "cogs" / "final_interaction_policy.py").read_text(encoding="utf-8")
    start = source.index("async def _send_plain_interaction_error")
    end = source.index("\n\ndef install(", start)
    block = source[start:end]

    assert "_slash_error_text" in block
    assert "sentrix_embeds.error(" not in block
    assert "sentrix_embeds.warning(" not in block
    assert "panels.depuis_embed(" not in block
    assert '"Une erreur est survenue. Merci de réessayer."' in block


def test_clear_is_forced_to_raw_text_everywhere():
    moderation = (ROOT / "cogs" / "moderation.py").read_text(encoding="utf-8")
    policy = (ROOT / "cogs" / "final_interaction_policy.py").read_text(encoding="utf-8")

    start = moderation.index('async def clear(')
    end = moderation.index("\n    @staticmethod", start)
    block = moderation[start:end]

    assert "panels.texte_court" not in block
    assert "ctx.channel.send(" in block
    assert "edit_original_response(content=texte)" in block
    assert '"clear"' in policy.split("PLAIN_ROOTS", 1)[1].split("\n", 2)[0]
