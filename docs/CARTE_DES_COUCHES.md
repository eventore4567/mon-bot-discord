# Carte des couches de SentriX

Généré par `tools/carte_des_couches.py` — ne pas modifier à la main.

Une « couche », c'est un fichier qui remplace au démarrage une fonction d'un autre
module (souvent en l'enveloppant). Plusieurs couches sur la même fonction : chaque
appel les traverse toutes, et il suffit qu'une seule plante (ou change de signature)
pour que la fonction ne marche plus — c'est l'origine des bugs « l'insulte n'est
pas avertie » et « l'IA ne répond pas à une image » de novembre 2026.

**380 fonctions remplacées, 784 remplacements au total.**

## Fonctions remplacées par au moins deux fichiers

| Couches | Fonction | Fichiers |
|---:|---|---|
| 55 | `build_app` | admin_only_dashboard.py, bot_directory_stats_v44.py, brand_avatar_v39.py, community_growth.py, dashboard_control_center_v3.py, dashboard_growth_control_v12.py, dashboard_guidance_v56.py, dashboard_ha_proxy_v1.py, dashboard_instance_runtime.py, dashboard_ops_suite.py, dashboard_ops_suite_fix.py, dashboard_ops_suite_plus.py, dashboard_polish.py, dashboard_product_ui_v18.py, dashboard_product_v18.py, dashboard_profile_images.py, dashboard_server_tools.py, dashboard_system_features.py, dashboard_v60_diagnostics.py, dashboard_v62_dense.py, dashboard_verification_v6.py, database_dashboard.py, design_setup_dashboard.py, discordbotlist_vote_webhook_v47.py, dm_panel.py, embed_center.py, embed_dashboard.py, engagement_hub.py, enterprise_suite.py, feature_control_v36.py, feature_suite_dashboard_v37.py, giveaway_antialt.py, giveaway_dashboard_v101.py, growth_referrals_v43.py, health_runtime_v45.py, log_settings_dashboard_v32.py, marketing_growth_indexing_v40.py, marketing_growth_v40.py, marketing_growth_v42.py, operations_center.py, owner_server_manager.py, persistent_dashboard_sessions.py, platform_v10.py, platform_v4.py, public_commands_v46.py, public_error_pages_v1.py, sentrix_premium_catalog.py, seo_v38.py, setup_center.py, setup_center_security_v2.py, setup_dashboard.py, ticket_buttons_editor_v53.py, ticket_center_v35.py, ticket_ping_dashboard.py, topgg_import_v45.py |
| 28 | `send` | command_response_guard.py, command_visuals.py, community_v32.py, community_v33.py, community_v34.py, control_center_v3.py, deferred_context_response_guard.py, final_interaction_policy.py, me_single_panel.py, plain_response_policy.py, premium_style_runtime.py, premium_ui_v81.py, production_embed_log_repair.py, profile_embed_guard.py, reply_reference_fix.py, setup_v2_core.py, top_banner_guard.py, unified_command_panels.py, v17_user_facing_hotfix.py |
| 27 | `INDEX_HTML` | __init__.py, advanced_mode_guide.py, community_card_polish.py, community_v3.py, dashboard_accessibility.py, dashboard_confirm_modal_v47.py, dashboard_control_center.py, dashboard_deeplinks.py, dashboard_focus_loading_v1.py, dashboard_frontend_freeze_v55.py, dashboard_growth_control_v12.py, dashboard_growth_control_v12_fix.py, dashboard_intelligent_ux.py, dashboard_ops_suite.py, dashboard_oxyde_theme.py, dashboard_premium_ui_v4.py, dashboard_profile_images.py, dashboard_safe_plus.py, dashboard_section_variants_v5.py, dashboard_simple_mode.py, dashboard_simple_mode_switch_fix.py, dashboard_v21.py, dashboard_v2_home.py, dashboard_v60_features_inline.py, dashboard_v61_postfix.py, dashboard_v62_dense.py, dashboard_verification_v6.py |
| 14 | `on_error` | bot_v16_commands.py, command_error_release_v41.py, command_observability_v9.py, community_v34.py, final_error_embed_v5.py, final_interaction_policy.py, global_command_error_guard.py, operations_center.py, production_observability_v9.py, sentrix_panels.py, slash_error_completion_guard.py, user_facing_hygiene.py |
| 13 | `build_embed` | automatic_verification_v5.py, control_center_v3_language.py, control_center_v3_ui_fix.py, control_center_v4.py, honeypot_verification_v48.py, language_official_bridge.py, language_runtime.py, setup_experience_v2.py, setup_invitations.py, setup_oxyde_style.py, setup_v2_completion.py, setup_v2_ui.py, ticket_ping_role.py |
| 13 | `params` | command_runtime_hardening_v18.py, community_v3.py, community_v31.py, emoji_name_lookup.py, emoji_unicode_asset_fix.py, member_data_retention_v17.py, profile_oxyde_runtime.py, sentrix_v21.py, visual_experience_v5.py |
| 10 | `generate` | ai_api_hotfix.py, ai_context_v9.py, ai_disable_guard.py, ai_personality_final.py, ai_reliability.py, bot_excellence_runtime.py, bot_mastery_runtime.py, bot_v12_machine.py, community_v33.py, natural_music_intent_guard.py |
| 9 | `BAR` | logs_unified_v6.py, ping_final_style.py, plain_text_all_extension.py, sentrix_runtime.py, sentrix_visual_cleanup.py, wide_compact_v6.py |
| 9 | `_safe_slash_health` | command_error_probe.py, deferred_context_response_guard.py, interaction_transport_guard.py, live_log_delivery_v5.py, log_listener_guarantee_v51.py, production_embed_log_repair.py, production_embed_log_repair_v3.py, slash_error_completion_guard.py, stale_discord_app_detector.py |
| 9 | `evaluate` | ban_command_whitelist.py, permission_setup_hardening_v65.py, setup_simple_v68.py |
| 9 | `on_command_error` | bot_v16_commands.py, command_integrity_v18.py, error_experience_v3.py, final_error_embed_v5.py, global_command_error_guard.py, plain_text_all_extension.py, runtime_consistency_v57.py, setup_invitations.py, user_facing_hygiene.py |
| 8 | `interaction_check` | command_channel_gate.py, command_hardening_v41.py, community_v32.py, dashboard_control_center_v3.py, dashboard_ops_suite.py, permission_guard.py, sentrix_panels.py, v17_ai_economy_games.py |
| 8 | `invoke` | bot_v15_runtime.py, command_final_guard_v76.py, final_interaction_policy.py, plain_response_policy.py, prefix_deprecation.py, production_embed_log_repair_v3.py, setup_auto_fix.py |
| 8 | `send_message` | community_v34.py, final_interaction_policy.py, plain_response_policy.py, premium_style_runtime.py, setup_invitations.py, setup_v2_core.py, top_banner_guard.py, unified_command_panels.py |
| 8 | `send_sentrix_reply` | ai_api_hotfix.py, ai_disable_guard.py, ai_reliability.py, ai_reply_recovery.py, bot_experience_v5.py, bot_experience_v6.py, sentrix_intelligent_ux.py, setup_v2_runtime.py |
| 7 | `_base` | command_visuals.py, community_v32.py, sentrix_runtime.py, sentrix_visual_cleanup.py, top_command_banners.py, wide_compact_v6.py |
| 7 | `create_ticket` | community_v3.py, community_v31.py, sentrix_intelligent_ux.py, sentrix_v22.py, setup_v2_core.py, ticket_claim_security.py, ticket_ping_role.py |
| 7 | `render` | control_center_v3_language.py, control_center_v3_ui_fix.py, control_center_v4.py, language_official_bridge.py, setup_invitations.py, setup_v2_completion.py, setup_v2_ui.py |
| 7 | `render_page` | economy_import.py, feature_comparison.py, honeypot_verification_v48.py, language_runtime.py, setup_oxyde_style.py, soundboard_logs.py, ticket_ping_role.py |
| 7 | `send_log` | bot_tracker.py, community_v33.py, create_sentrix_v3.py, live_log_delivery_v5.py, premium_style_runtime.py, setup_v2_core.py, v17_tickets_logs.py |
| 7 | `voice_client` | ai.py, dashboard_api_music.py, music.py |
| 6 | `command` | community_game_panels.py, economy_panel_builder.py, sentrix_intelligent_ux.py, trace.py |
| 6 | `defer` | community_v33.py, community_v34.py, deferred_context_response_guard.py, final_interaction_policy.py, interaction_defer_safety_v21.py, setup_invitations.py |
| 6 | `get_settings` | ai_compatibility_v23.py, ai_reliability.py, bot_excellence_runtime.py, sentrix_v22.py |
| 5 | `edit` | final_interaction_policy.py, owner_sanction_immunity.py, plain_response_policy.py, premium_style_runtime.py, top_command_banners.py |
| 4 | `PANEL_BAR` | logs_unified_v6.py, plain_text_all_extension.py |
| 4 | `add_command` | common_command_names.py, no_cooldown_final.py, permission_guard.py, slash_command_budget.py |
| 4 | `create_embed` | community_v32.py, premium_style_runtime.py, sentrix_runtime.py, sentrix_visual_cleanup.py |
| 4 | `current` | bot_mastery_runtime.py, music.py |
| 4 | `edit_message` | final_interaction_policy.py, plain_response_policy.py, premium_style_runtime.py, top_command_banners.py |
| 4 | `edit_original_response` | final_interaction_policy.py, plain_response_policy.py, premium_style_runtime.py, top_command_banners.py |
| 4 | `format_command_line` | command_clarity.py, common_command_names.py, help_complete.py, user_facing_hygiene.py |
| 4 | `handle_index` | __init__.py, brand_avatar_v39.py, dashboard_frontend_freeze_v55.py, dashboard_live_response_v15.py |
| 4 | `punish_nuker` | antinuke_emergency_v55.py, antinuke_rollback.py, production_alert_noise_fix.py, security_v2_runtime.py |
| 4 | `reward_game_winner` | bot_excellence_runtime.py, bot_mastery_runtime.py, game_seasons_v9.py, stability_runtime.py |
| 4 | `send_setup` | setup_components_v73.py, setup_experience_v74.py, setup_invitations.py |
| 4 | `style_embed` | command_style_v2.py, community_v32.py, premium_style_runtime.py, sentrix_visual_cleanup.py |
| 3 | `_build_system_instructions` | ai_reply_recovery.py, community_v3.py, community_v32.py |
| 3 | `_compact_command_line` | command_clarity.py, help_clean_style.py, user_facing_hygiene.py |
| 3 | `_guild_metrics` | community_v3.py, dashboard_recovery_v54.py, sentrix_ultimate.py |
| 3 | `_help_home` | final_runtime_polish.py, help_clean_style.py |
| 3 | `_manageable_guild` | dashboard_ops_suite_plus.py, dashboard_product_v18.py, dashboard_recovery_v54.py |
| 3 | `_send` | bot_tracker.py, create_sentrix_v3.py, setup_v2_core.py |
| 3 | `build_server` | runtime_fix_v1.py, server_builder_moderation_space.py, server_builder_ready_setup.py |
| 3 | `close_ticket` | logs_unified_v6.py, sentrix_ultimate.py, ticket_claim_security.py |
| 3 | `duration_s` | automod.py |
| 3 | `execute` | member_data_retention_v17.py, runtime_finish_v94.py, v17_shared.py |
| 3 | `generate_image` | ai_disable_guard.py, bot_excellence_runtime.py, bot_mastery_runtime.py |
| 3 | `handle_guilds` | dashboard_ops_suite_plus.py, dashboard_product_v18.py, dashboard_recovery_v54.py |
| 3 | `handle_health` | ai_api_hotfix.py, health_runtime_v45.py, production_health.py |
| 3 | `handle_setup_center` | setup_center_exclusive.py, setup_center_explanations.py, setup_center_search.py |
| 3 | `log_action` | logs_unified_v6.py, runtime_finish_v84.py, ticket_claim_security.py |
| 3 | `log_embed` | log_compact_final.py, sentrix_runtime.py, sentrix_visual_cleanup.py |
| 3 | `normalize_log` | log_compact_final.py, sentrix_runtime.py, sentrix_visual_cleanup.py |
| 3 | `reply` | premium_style_runtime.py, reply_reference_fix.py |
| 3 | `update_setting` | ai_reliability.py, bot_excellence_runtime.py, sentrix_v22.py |
| 2 | `_administrator_member` | admin_only_dashboard.py, dashboard_runtime_patch.py |
| 2 | `_build_home_embed` | setup_experience_v2.py, setup_oxyde_style.py |
| 2 | `_cache_message` | setup_v2_core.py, setup_v2_runtime.py |
| 2 | `_category_for` | help_category_rework.py, user_facing_hygiene.py |
| 2 | `_command_usage` | common_command_names.py, user_facing_hygiene.py |
| 2 | `_delete_and_warn` | content_filter_policy.py, forbidden_words_ui.py |
| 2 | `_force_rich_args` | command_style_v2.py, send_argument_safety_v20.py |
| 2 | `_health_alert` | community_v33.py, production_alert_noise_fix.py |
| 2 | `_home` | setup_simple_v68.py, setup_ticket_autoconfig_v72.py |
| 2 | `_log_embed` | log_compact_final.py, sentrix_visual_cleanup.py |
| 2 | `_normalize_log` | log_compact_final.py, sentrix_visual_cleanup.py |
| 2 | `_open_setup_panel` | language_setup_finalizer.py |
| 2 | `_prepare_and_generate` | community_v3.py, community_v34.py |
| 2 | `_prune_redundant_commands` | help_v8_final_guard.py, integrity_hardening.py |
| 2 | `_render_home` | setup_experience_v2.py, setup_oxyde_style.py |
| 2 | `action` | automod.py, forbidden_words_ui.py |
| 2 | `aliases` | command_integrity_v18.py |
| 2 | `ask_ai` | community_v3.py, natural_music_intent_guard.py |
| 2 | `ban` | owner_sanction_immunity.py |
| 2 | `btn_claim` | community_v31.py, ticket_claim_security.py |
| 2 | `btn_transfer` | community_v31.py, integrity_hardening.py |
| 2 | `btn_unclaim` | community_v31.py, ticket_claim_security.py |
| 2 | `build_help_home` | dashboard_access.py, help_complete.py |
| 2 | `build_server_context` | bot_v10.py, bot_v12_machine.py |
| 2 | `close` | bot_mastery_runtime.py, production_phase_runtime.py |
| 2 | `command_usage` | bot_v16_commands.py, user_facing_hygiene.py |
| 2 | `content` | ai.py, sentrix_plus.py |
| 2 | `convert` | bot_v16_commands.py, common_command_names.py |
| 2 | `create_log_channels` | runtime_fix_v1.py, setup_auto_fix.py |
| 2 | `error_message` | ai_disable_guard.py, v17_ai_economy_games.py |
| 2 | `error_title` | ai_disable_guard.py, v17_ai_economy_games.py |
| 2 | `get_conversation_history` | bot_mastery_runtime.py, bot_v12_machine.py |
| 2 | `get_log_setting` | bot_tracker.py, create_sentrix_v3.py |
| 2 | `handle_control_button` | ticket_claim_security.py, ticket_controls_minimal.py |
| 2 | `infractions` | automod.py, forbidden_words_ui.py |
| 2 | `install` | plain_text_all_extension.py, v17_user_facing_hotfix.py |
| 2 | `is_bot_creator` | bot_v14_core.py, runtime_quality_v25.py |
| 2 | `is_error_code` | ai_disable_guard.py, v17_ai_economy_games.py |
| 2 | `is_mod_or_permission` | ban_command_whitelist.py, v17_shared.py |
| 2 | `kick` | owner_sanction_immunity.py |
| 2 | `load_extension` | __init__.py, command_runtime_hardening_v18.py |
| 2 | `module_statuses` | setup_invitations.py, setup_v2_ui.py |
| 2 | `name` | slash_catalog.py |
| 2 | `permission_page` | permission_setup_hardening_v65.py, setup_v2_ui.py |
| 2 | `pick_reasoning_effort` | ai_api_hotfix.py, ai_reliability.py |
| 2 | `production_v9_health_snapshot` | command_observability_v9.py, production_observability_v9.py |
| 2 | `record_nuke_action` | security_runtime_hardening.py, security_v2_runtime.py |
| 2 | `recovery_key` | music.py |
| 2 | `refresh` | control_center_v3_ui_fix.py, setup_components_v73.py |
| 2 | `requested_by` | search.py |
| 2 | `rollback_actor` | production_alert_noise_fix.py, security_v2_runtime.py |
| 2 | `search_commands` | common_command_names.py, help_complete.py |
| 2 | `security_headers` | embed_center.py, embed_dashboard.py |
| 2 | `send_help` | help_complete_v79.py, help_components_v77.py |
| 2 | `send_messages` | sentrix_ultimate.py, ticket_claim_security.py |
| 2 | `set_settings` | bot_excellence_runtime.py, sentrix_v22.py |
| 2 | `start_ticket_flow` | sentrix_v22.py, setup_ticket_autoconfig_v72.py |
| 2 | `style_existing` | sentrix_visual_cleanup.py, wide_compact_v6.py |
| 2 | `style_view` | command_style_v2.py, community_v32.py |
| 2 | `template_name` | embed_builder.py |
| 2 | `text_channel` | dashboard_api_music.py, music.py |
| 2 | `title` | premium_style_runtime.py, premium_ui_v82.py |

## Ordre de la réorganisation

Chaque fonction de ce tableau devient UNE implémentation, dans le module qui la
possède, et les couches correspondantes sont supprimées. Toujours avec la suite de
tests complète au vert, une PR par fonction (ou par petit groupe).

