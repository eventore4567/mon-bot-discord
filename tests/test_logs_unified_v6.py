from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
V6 = ROOT / "cogs" / "logs_unified_v6.py"
GUARD = ROOT / "cogs" / "slash_error_completion_guard.py"
SYNC = ROOT / "cogs" / "generated_logs_sync.py"

# Ce gate protège les contrats visuels et de routage de la couche V6 finale.

def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v6_sources_compile():
    for path in (V6, GUARD, SYNC):
        compile(read(path), str(path), "exec")


def test_v6_is_the_final_runtime_layer():
    source = read(GUARD)
    final_error = source.index("final_error_embed_v5.install(bot)")
    v6_install = source.index("await logs_unified_v6.install(bot)")
    assert v6_install > final_error


def test_official_structure_has_deleted_files_route():
    source = read(V6)
    assert '"files",\n    "log_files",\n    "logs-dossiers"' in source
    assert 'log_service.LOG_TYPES["files"]' in source
    # CONFIG_TO_LOG_TYPE a disparu de cogs/logs.py : chaque listener passe desormais son
    # type d'evenement canonique. On verifie donc le routage reel plutot que la table.
    from utils.log_categories import category_for
    assert category_for("file_delete") == "files"
    assert category_for("file_upload") == "files"
    from cogs.generated_logs_sync import LOG_CHANNEL_ALIASES
    # Chaque categorie a ses propres alias de salon. "logs-salons" appartient a Salons,
    # pas a Serveur : l'ancienne cle fourre-tout log_server melangeait les deux.
    assert LOG_CHANNEL_ALIASES["files"] == ("logs-dossiers", "logs-fichiers", "logs-files")
    assert "logs-salons" in LOG_CHANNEL_ALIASES["channels"]
    assert "logs-salons" not in LOG_CHANNEL_ALIASES["server"]
    # Un alias ne doit jamais appartenir a deux categories : le meme salon serait
    # retrouve pour deux routes selon l'ordre d'iteration.
    seen: dict[str, str] = {}
    for category, aliases in LOG_CHANNEL_ALIASES.items():
        for alias in aliases:
            assert alias not in seen, f"{alias} partage entre {seen.get(alias)} et {category}"
            seen[alias] = category


def test_separator_is_longer_and_shared():
    source = read(V6)
    match = re.search(r'^LOG_BAR = "([━]+)"$', source, re.MULTILINE)
    assert match, "LOG_BAR V6 manquante"
    assert len(match.group(1)) >= 44
    assert "embeds.BAR = LOG_BAR" in source
    assert "log_compact_final.PANEL_BAR = LOG_BAR" in source


def test_channel_name_survives_channel_deletion():
    source = read(V6)
    assert "_CHANNEL_NAMES" in source
    assert "_remember_channel(channel)" in source
    assert 'return f"{channel.mention} • `#{_clean_channel_name(channel.name)}`"' in source
    assert 'return f"`#{known}`"' in source
    assert "# inconnu" not in source.casefold()


def test_deleted_attachments_are_archived_in_logs_dossiers():
    source = read(V6)
    assert "attachment.to_file(use_cached=True)" in source
    assert '"deleted_files"' in source
    assert 'log_transport_v52._resolve_setting(\n            bot, guild, "files"' in source
    assert 'kwargs["files"] = files' in source


def test_ticket_transcript_is_a_button_not_a_permanent_gray_attachment():
    source = read(V6)
    assert "CREATE TABLE IF NOT EXISTS ticket_transcripts" in source
    assert 'label="Télécharger la transcript"' in source
    assert 'custom_id=f"sentrix:ticket-transcript:{int(ticket_id)}"' in source
    assert 'prefix = "sentrix:ticket-transcript:"' in source
    assert '"Transcript", "Disponible avec le bouton ci-dessous."' in source
    # Le fichier est généré uniquement à la demande/DM ; l'envoi du log passe par send_log + view.
    close_block = source[source.index("async def close_ticket_v6"):source.index("def _patch_raw_file_recovery")]
    assert '"tickets",\n            panel,\n            view=_ticket_actions' in close_block


def test_reset_moves_all_ticket_types_and_preserves_unrelated_staff_channels():
    source = read(V6)
    assert "UPDATE ticket_types SET log_channel_id = ? WHERE guild_id = ?" in source
    assert "_cleanup_obsolete_sentrix_logs" in source
    names_block = source[source.index("LEGACY_LOG_NAMES = {"):source.index("_CHANNEL_NAMES:")]
    assert '"moderator-only"' not in names_block
    assert 'name not in LEGACY_LOG_NAMES' in source
    assert "sentrix_owned" in source


if __name__ == "__main__":
    test_v6_sources_compile()
    test_v6_is_the_final_runtime_layer()
    test_official_structure_has_deleted_files_route()
    test_separator_is_longer_and_shared()
    test_channel_name_survives_channel_deletion()
    test_deleted_attachments_are_archived_in_logs_dossiers()
    test_ticket_transcript_is_a_button_not_a_permanent_gray_attachment()
    test_reset_moves_all_ticket_types_and_preserves_unrelated_staff_channels()
    print("logs unified v6 contracts: ok")
