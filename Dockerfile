FROM denoland/deno:bin-2.9.5 AS deno
# FFmpeg/FFprobe statiques : évitent l'installation apt de >200 paquets Debian.
# Le précédent build Railway standby échouait avec « No space left on device »
# pendant apt-get install ffmpeg ; les deux binaires restent disponibles.
FROM mwader/static-ffmpeg:8.1.2 AS ffmpeg_static
FROM python:3.11-slim

# yt-dlp utilise Deno pour résoudre les challenges YouTube.
COPY --from=deno /deno /usr/local/bin/deno
COPY --from=ffmpeg_static /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg_static /ffprobe /usr/local/bin/ffprobe

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Barrière de syntaxe : aucune erreur Python dans les couches critiques ne doit
# atteindre le runtime Railway.
RUN python -m compileall -q core cogs utils web main.py railway_boot.py railway_ha_boot.py railway_ha_product_boot_v8.py

# Barrière de qualité micro-kernel exécutée à chaque build primaire : une release
# qui casse l'isolation, la readiness, les circuits ou le reload reste hors prod.
RUN python -m pytest -q \
    tests/test_module_kernel.py \
    tests/test_module_runtime.py \
    tests/test_module_supervisor.py \
    tests/test_module_gate.py \
    tests/test_module_policy.py \
    tests/test_health_runtime_module_readiness.py \
    tests/test_runtime_observability_module_health.py \
    tests/test_runtime_attribution.py \
    tests/test_tickets_autoclose_resilience.py \
    tests/test_ticket_open_concurrency.py \
    tests/test_ticket_panel_atomic_republish.py \
    tests/test_ticket_panel_restore_atomic.py \
    tests/test_logs_bulk_delete_resilience.py \
    tests/test_moderation_logging_resilience.py \
    tests/test_automod_enforcement_resilience.py \
    tests/test_security_message_bypass_regression.py \
    tests/test_security_duplicate_short_replies.py \
    tests/test_antilink_delete_notice.py \
    tests/test_automod_idempotent_sanctions_v131.py \
    tests/test_purge_queue.py \
    tests/test_scale_startup.py \
    tests/test_pg_dialect.py \
    tests/test_pg_ha_boot.py \
    tests/test_cluster.py \
    tests/test_slash_slow_defer.py \
    tests/test_pvp_engine.py \
    tests/test_fun_social.py \
    tests/test_command_usage.py \
    tests/test_command_refs.py \
    tests/test_raid_verification_recovery_v130.py \
    tests/test_automod_log_manage_style.py \
    tests/test_sentrix_trace_style.py \
    tests/test_sentrix_core_style.py \
    tests/test_sentrix_native_interactive_surfaces.py \
    tests/test_plain_error_messages.py \
    tests/test_plain_text_mentions.py \
    tests/test_units_and_plain_errors.py \
    tests/test_short_command_names.py \
    tests/test_canonical_command_surface.py \
    tests/test_command_surface_v110.py \
    tests/test_slash_catalog.py \
    tests/test_slash_catalog_prefix_migration.py \
    tests/test_welcome_autoroles.py \
    tests/test_command_setup_prompt.py \
    tests/test_setup_advanced_moderation_ui.py \
    tests/test_help_short_names.py \
    tests/test_command_registry_audit.py \
    tests/test_discord_command_publish_audit.py \
    tests/test_dashboard_feedback_reports.py \
    tests/test_dashboard_logs_visible_v1.py \
    tests/test_rules_readonly_ai_advice.py \
    tests/test_channel_access_preview_confirmation.py \
    tests/test_published_rules_lock_v119.py \
    tests/test_voice_verification_lock.py \
    tests/test_dashboard_json_snowflakes.py \
    tests/test_guild_departure_notify.py \
    tests/test_verification_panel_recovery.py \
    tests/test_ai_disable_guard_loading.py \
    tests/test_ai_native_discord_reply_v5.py \
    tests/test_ai_actions_permissions.py \
    tests/test_music_matcher.py \
    tests/test_music_manager.py \
    tests/test_music_provider_url_matching.py \
    tests/test_music_voice_persistence.py \
    tests/test_music_cog.py \
    tests/test_music_playlists_v108.py \
    tests/test_music_playlist_persistence.py \
    tests/test_games_runtime_core.py \
    tests/test_duel_invitation_games.py \
    tests/test_bossfight_economy_animation.py \
    tests/test_game_visuals.py \
    tests/test_community_text_races_async.py \
    tests/test_game_stakes.py \
    tests/test_services_economy.py \
    tests/test_economy_race_conditions.py \
    tests/test_v25_quality.py

# Port du dashboard web intégré (voir web/dashboard.py) — Railway fournit sa propre
# variable PORT au runtime, cette ligne ne sert que de documentation pour Docker.
EXPOSE 8080

# V98 installe la nouvelle arborescence slash puis délègue au bootstrap Railway historique.
# Le dashboard démarre toujours avant Discord afin de préserver le healthcheck existant.
CMD ["python3", "sentrix_v98_boot.py"]
