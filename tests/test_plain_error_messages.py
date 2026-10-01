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
