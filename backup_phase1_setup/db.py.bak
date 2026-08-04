"""
Couche d'accès à la base de données SQLite (async, via aiosqlite).
Toutes les données du bot (sanctions, tickets, économie, niveaux, config, etc.)
sont stockées ici. Aucune adresse IP n'est jamais collectée ni stockée.
"""

import aiosqlite
import os
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id INTEGER PRIMARY KEY,
    language TEXT DEFAULT 'fr',
    prefix TEXT DEFAULT '+',
    log_channel INTEGER,
    mod_role INTEGER,
    admin_role INTEGER,
    mute_role INTEGER,
    welcome_channel INTEGER,
    welcome_message TEXT,
    goodbye_channel INTEGER,
    goodbye_message TEXT,
    rules_channel INTEGER,
    verification_channel INTEGER,
    verification_role INTEGER,
    verify_role INTEGER,
    security_level TEXT DEFAULT 'moyen',
    xp_multiplier REAL DEFAULT 1.0,
    xp_channel_disabled TEXT DEFAULT '',
    level_message TEXT,
    ticket_category INTEGER,
    ticket_log_channel INTEGER,
    autorole INTEGER,
    level_channel INTEGER,
    suggest_channel INTEGER,
    announce_channel INTEGER,
    giveaway_channel INTEGER,
    log_messages INTEGER,
    log_members INTEGER,
    log_voice INTEGER,
    log_roles INTEGER,
    log_server INTEGER,
    log_automod INTEGER,
    log_moderation INTEGER,
    warn_role INTEGER,
    warn_ban_threshold INTEGER DEFAULT 3,
    ticket_delete_delay INTEGER DEFAULT 30,
    ticket_transcript_dm INTEGER DEFAULT 1,
    ticket_rating_enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    moderator_id INTEGER,
    reason TEXT,
    timestamp INTEGER
);

CREATE TABLE IF NOT EXISTS tempactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    action TEXT,
    expires_at INTEGER
);

CREATE TABLE IF NOT EXISTS blacklist_words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    word TEXT
);

CREATE TABLE IF NOT EXISTS blacklist_users (
    guild_id INTEGER,
    user_id INTEGER,
    reason TEXT,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS whitelist_domains (
    guild_id INTEGER,
    domain TEXT,
    PRIMARY KEY (guild_id, domain)
);

CREATE TABLE IF NOT EXISTS automod_settings (
    guild_id INTEGER PRIMARY KEY,
    antispam INTEGER DEFAULT 0,
    antilink INTEGER DEFAULT 0,
    antiinvite INTEGER DEFAULT 0,
    antimention INTEGER DEFAULT 0,
    anticaps INTEGER DEFAULT 0,
    antiemoji INTEGER DEFAULT 0,
    antiraid INTEGER DEFAULT 0,
    antibot INTEGER DEFAULT 0,
    antiaccount INTEGER DEFAULT 0,
    antiscam INTEGER DEFAULT 0,
    antinuke INTEGER DEFAULT 0,
    escalation INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS automod_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    filter_name TEXT,
    action TEXT,
    reason TEXT,
    timestamp INTEGER
);

CREATE TABLE IF NOT EXISTS automod_exempt_roles (
    guild_id INTEGER,
    role_id INTEGER,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS antinuke_whitelist (
    guild_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS disabled_commands (
    guild_id INTEGER,
    command_name TEXT,
    PRIMARY KEY (guild_id, command_name)
);

CREATE TABLE IF NOT EXISTS ignored_channels (
    guild_id INTEGER,
    channel_id INTEGER,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    channel_id INTEGER,
    user_id INTEGER,
    status TEXT DEFAULT 'ouvert',
    category TEXT DEFAULT 'general',
    priority TEXT DEFAULT 'normale',
    claimed_by INTEGER,
    created_at INTEGER,
    closed_at INTEGER,
    rating INTEGER,
    type_id INTEGER,
    locked INTEGER DEFAULT 0,
    last_activity_at INTEGER
);

CREATE TABLE IF NOT EXISTS ticket_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER,
    author_id INTEGER,
    note TEXT,
    timestamp INTEGER
);

CREATE TABLE IF NOT EXISTS ticket_panels (
    guild_id INTEGER,
    channel_id INTEGER,
    message_id INTEGER
);

CREATE TABLE IF NOT EXISTS economy (
    guild_id INTEGER,
    user_id INTEGER,
    cash INTEGER DEFAULT 0,
    bank INTEGER DEFAULT 0,
    last_daily INTEGER DEFAULT 0,
    last_weekly INTEGER DEFAULT 0,
    last_work INTEGER DEFAULT 0,
    last_crime INTEGER DEFAULT 0,
    last_beg INTEGER DEFAULT 0,
    last_rob INTEGER DEFAULT 0,
    protected_until INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS shop_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    name TEXT,
    price INTEGER,
    description TEXT,
    role_id INTEGER
);

CREATE TABLE IF NOT EXISTS inventory (
    guild_id INTEGER,
    user_id INTEGER,
    item_name TEXT,
    quantity INTEGER DEFAULT 1,
    UNIQUE (guild_id, user_id, item_name)
);

CREATE TABLE IF NOT EXISTS levels (
    guild_id INTEGER,
    user_id INTEGER,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 0,
    last_message_time INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS level_roles (
    guild_id INTEGER,
    level INTEGER,
    role_id INTEGER,
    PRIMARY KEY (guild_id, level)
);

CREATE TABLE IF NOT EXISTS profiles (
    guild_id INTEGER,
    user_id INTEGER,
    bio TEXT,
    background TEXT,
    reputation INTEGER DEFAULT 0,
    last_rep INTEGER DEFAULT 0,
    birthday TEXT,
    married_to INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    channel_id INTEGER,
    message_id INTEGER,
    prize TEXT,
    winners_count INTEGER DEFAULT 1,
    status TEXT DEFAULT 'actif',
    end_at INTEGER,
    winners TEXT,
    required_role_id INTEGER,
    required_level INTEGER,
    excluded_role_id INTEGER,
    bonus_role_id INTEGER,
    bonus_entries INTEGER DEFAULT 2,
    created_by INTEGER,
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS giveaway_entries (
    giveaway_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY (giveaway_id, user_id)
);

CREATE TABLE IF NOT EXISTS giveaway_blacklist (
    guild_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    channel_id INTEGER,
    message_id INTEGER,
    name TEXT,
    description TEXT,
    start_at INTEGER,
    status TEXT DEFAULT 'planifie',
    created_by INTEGER,
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS event_participants (
    event_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY (event_id, user_id)
);

CREATE TABLE IF NOT EXISTS tournaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    name TEXT,
    max_participants INTEGER DEFAULT 16,
    status TEXT DEFAULT 'inscriptions',
    bracket_data TEXT,
    created_by INTEGER,
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS tournament_participants (
    tournament_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY (tournament_id, user_id)
);

CREATE TABLE IF NOT EXISTS reaction_roles (
    guild_id INTEGER,
    message_id INTEGER,
    emoji TEXT,
    role_id INTEGER
);

CREATE TABLE IF NOT EXISTS autorole (
    guild_id INTEGER,
    role_id INTEGER,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS verified_users (
    guild_id INTEGER,
    user_id INTEGER,
    verified_at INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS command_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    command_name TEXT,
    timestamp INTEGER
);

CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    message_id INTEGER,
    content TEXT,
    status TEXT DEFAULT 'en_attente',
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS bug_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    content TEXT,
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    channel_id INTEGER,
    guild_id INTEGER,
    text TEXT,
    trigger_at INTEGER,
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS pets (
    guild_id INTEGER,
    user_id INTEGER,
    name TEXT DEFAULT 'Compagnon',
    level INTEGER DEFAULT 1,
    hunger INTEGER DEFAULT 100,
    last_fed INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    name TEXT,
    tracks TEXT
);

CREATE TABLE IF NOT EXISTS message_counts (
    guild_id INTEGER,
    user_id INTEGER,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS voice_totals (
    guild_id INTEGER,
    user_id INTEGER,
    seconds INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS growth_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    member_count INTEGER,
    timestamp INTEGER
);

CREATE TABLE IF NOT EXISTS bot_managers (
    guild_id INTEGER,
    user_id INTEGER,
    added_by INTEGER,
    added_at INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS command_blacklist (
    user_id INTEGER PRIMARY KEY,
    reason TEXT,
    blacklisted_by INTEGER,
    blacklisted_at INTEGER
);

CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS command_aliases (
    guild_id INTEGER,
    alias TEXT,
    command_name TEXT,
    PRIMARY KEY (guild_id, alias)
);

CREATE TABLE IF NOT EXISTS member_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    member_id INTEGER,
    inviter_id INTEGER,
    invite_code TEXT,
    joined_at INTEGER,
    left_at INTEGER
);

-- ---------------------------------------------------------------------------
-- Outils de sécurité avancés : quarantaine, snapshots de rôles, sauvegarde
-- de la structure du serveur, audit des permissions (cogs/security_tools.py).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS role_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    role_ids TEXT,
    label TEXT DEFAULT '',
    created_by INTEGER,
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS quarantines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    snapshot_id INTEGER,
    reason TEXT,
    moderator_id INTEGER,
    created_at INTEGER,
    expires_at INTEGER,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS server_backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    label TEXT DEFAULT '',
    data_json TEXT,
    created_by INTEGER,
    created_at INTEGER
);

-- ---------------------------------------------------------------------------
-- Système de tickets v2 : entièrement piloté par Discord (cogs/tickets.py),
-- rien n'est écrit en dur dans le code. Un serveur peut avoir plusieurs panels,
-- chaque panel plusieurs types de tickets, chaque type son propre formulaire.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ticket_panels_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    name TEXT DEFAULT 'Panel',
    title TEXT DEFAULT '🎫 Support',
    description TEXT DEFAULT 'Choisissez une option ci-dessous pour ouvrir un ticket.',
    color INTEGER,
    image_url TEXT,
    thumbnail_url TEXT,
    footer_text TEXT,
    channel_id INTEGER,
    message_id INTEGER,
    style TEXT DEFAULT 'select',
    max_per_member INTEGER DEFAULT 1,
    enabled INTEGER DEFAULT 1,
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS ticket_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_id INTEGER,
    guild_id INTEGER,
    name TEXT DEFAULT 'Support',
    description TEXT DEFAULT '',
    emoji TEXT DEFAULT '🎫',
    button_label TEXT DEFAULT '',
    button_style TEXT DEFAULT 'blurple',
    staff_role_id INTEGER,
    category_id INTEGER,
    name_format TEXT DEFAULT 'ticket-{pseudo}',
    open_message TEXT DEFAULT '',
    max_per_member INTEGER DEFAULT 1,
    autoclose_hours INTEGER DEFAULT 0,
    log_channel_id INTEGER,
    mention_staff INTEGER DEFAULT 1,
    use_form INTEGER DEFAULT 0,
    position INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ticket_form_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_type_id INTEGER,
    position INTEGER DEFAULT 0,
    label TEXT DEFAULT 'Question',
    placeholder TEXT DEFAULT '',
    style TEXT DEFAULT 'short',
    required INTEGER DEFAULT 1,
    min_length INTEGER DEFAULT 0,
    max_length INTEGER DEFAULT 500
);

CREATE TABLE IF NOT EXISTS ticket_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER,
    question_label TEXT,
    answer TEXT
);

CREATE TABLE IF NOT EXISTS ticket_button_settings (
    guild_id INTEGER PRIMARY KEY,
    config_json TEXT
);
"""

# Index sur les colonnes les plus interrogées : indispensable pour qu'un serveur de
# plusieurs dizaines de milliers de membres reste rapide (sans ça, chaque requête
# devient un balayage complet de table au fur et à mesure que les données grossissent).
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings (guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_tempactions_expires ON tempactions (expires_at);
CREATE INDEX IF NOT EXISTS idx_tickets_guild_status ON tickets (guild_id, status);
CREATE INDEX IF NOT EXISTS idx_tickets_channel ON tickets (channel_id);
CREATE INDEX IF NOT EXISTS idx_giveaways_status_end ON giveaways (status, end_at);
CREATE INDEX IF NOT EXISTS idx_giveaways_message ON giveaways (message_id);
CREATE INDEX IF NOT EXISTS idx_events_status_start ON events (status, start_at);
CREATE INDEX IF NOT EXISTS idx_command_logs_guild_cmd ON command_logs (guild_id, command_name);
CREATE INDEX IF NOT EXISTS idx_reminders_trigger ON reminders (trigger_at);
CREATE INDEX IF NOT EXISTS idx_reaction_roles_msg ON reaction_roles (guild_id, message_id);
CREATE INDEX IF NOT EXISTS idx_member_invites_inviter ON member_invites (guild_id, inviter_id);
CREATE INDEX IF NOT EXISTS idx_member_invites_member ON member_invites (guild_id, member_id);
CREATE INDEX IF NOT EXISTS idx_levels_guild_rank ON levels (guild_id, level DESC, xp DESC);
CREATE INDEX IF NOT EXISTS idx_economy_guild_total ON economy (guild_id, (cash + bank) DESC);
CREATE INDEX IF NOT EXISTS idx_blacklist_words_guild ON blacklist_words (guild_id);
CREATE INDEX IF NOT EXISTS idx_automod_logs_guild_time ON automod_logs (guild_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_automod_logs_guild_user ON automod_logs (guild_id, user_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_role_snapshots_guild_user ON role_snapshots (guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_quarantines_active_expires ON quarantines (active, expires_at);
CREATE INDEX IF NOT EXISTS idx_quarantines_guild_user ON quarantines (guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_server_backups_guild ON server_backups (guild_id);
CREATE INDEX IF NOT EXISTS idx_ticket_panels_v2_guild ON ticket_panels_v2 (guild_id);
CREATE INDEX IF NOT EXISTS idx_ticket_types_panel ON ticket_types (panel_id);
CREATE INDEX IF NOT EXISTS idx_ticket_form_questions_type ON ticket_form_questions (ticket_type_id);
CREATE INDEX IF NOT EXISTS idx_ticket_answers_ticket ON ticket_answers (ticket_id);
"""

# Colonnes ajoutées à guild_config après sa création initiale : CREATE TABLE IF NOT EXISTS
# ne touche pas une table déjà existante, donc sur une base déjà en place (ex: un volume
# persistant sur l'hébergeur), ces nouvelles colonnes doivent être ajoutées manuellement
# via ALTER TABLE au démarrage. Voir Database._migrate().
GUILD_CONFIG_NEW_COLUMNS = {
    "log_messages": "INTEGER",
    "log_members": "INTEGER",
    "log_voice": "INTEGER",
    "log_roles": "INTEGER",
    "log_server": "INTEGER",
    "log_automod": "INTEGER",
    "log_moderation": "INTEGER",
    "warn_role": "INTEGER",
    "warn_ban_threshold": "INTEGER DEFAULT 3",
    "ticket_delete_delay": "INTEGER DEFAULT 30",
    "ticket_transcript_dm": "INTEGER DEFAULT 1",
    "ticket_rating_enabled": "INTEGER DEFAULT 1",
}

# Même principe que GUILD_CONFIG_NEW_COLUMNS, mais pour automod_settings : "escalation"
# a été ajoutée après la création initiale de la table.
AUTOMOD_SETTINGS_NEW_COLUMNS = {
    "escalation": "INTEGER DEFAULT 1",
}

# Même principe, pour la table tickets : "type_id" et "locked" ont été ajoutées avec
# le système de tickets v2 (panels/types/formulaires entièrement configurables).
TICKETS_NEW_COLUMNS = {
    "type_id": "INTEGER",
    "locked": "INTEGER DEFAULT 0",
    "last_activity_at": "INTEGER",
}


class Database:
    """Petit wrapper async autour d'aiosqlite, partagé par tous les cogs."""

    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        # guild_config est lu à peu près à CHAQUE message/arrivée/départ/log sur TOUT le bot
        # (welcome, autorole, salons de logs, préfixe...). Sur un serveur de plusieurs dizaines
        # ou centaines de milliers de membres, ça représente un très gros volume d'événements :
        # sans cache, chacun ferait un aller-retour SQLite pour une ligne qui ne change presque
        # jamais. On garde donc la config de chaque serveur en mémoire, invalidée uniquement
        # quand elle est explicitement modifiée (set_guild_config / reset).
        self._guild_config_cache: dict[int, "aiosqlite.Row"] = {}

    async def connect(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        # WAL = lectures/écritures concurrentes sans se bloquer mutuellement.
        # synchronous=NORMAL = bon compromis vitesse/sécurité, recommandé avec WAL.
        # Ces deux réglages sont ce qui permet à SQLite de tenir la charge sur un
        # gros serveur (plusieurs milliers de membres actifs en même temps).
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.executescript(SCHEMA)
        await self._conn.executescript(INDEXES)
        await self._migrate()
        await self._conn.commit()

    async def _migrate(self):
        """Ajoute les colonnes manquantes si les tables existaient déjà avant leur
        introduction (utile si la base survit aux redéploiements, ex: volume persistant)."""
        cur = await self._conn.execute("PRAGMA table_info(guild_config)")
        existing = {row[1] for row in await cur.fetchall()}
        for column, col_type in GUILD_CONFIG_NEW_COLUMNS.items():
            if column not in existing:
                await self._conn.execute(f"ALTER TABLE guild_config ADD COLUMN {column} {col_type}")

        cur = await self._conn.execute("PRAGMA table_info(automod_settings)")
        existing_automod = {row[1] for row in await cur.fetchall()}
        for column, col_type in AUTOMOD_SETTINGS_NEW_COLUMNS.items():
            if column not in existing_automod:
                await self._conn.execute(f"ALTER TABLE automod_settings ADD COLUMN {column} {col_type}")

        cur = await self._conn.execute("PRAGMA table_info(tickets)")
        existing_tickets = {row[1] for row in await cur.fetchall()}
        for column, col_type in TICKETS_NEW_COLUMNS.items():
            if column not in existing_tickets:
                await self._conn.execute(f"ALTER TABLE tickets ADD COLUMN {column} {col_type}")

    async def close(self):
        if self._conn:
            await self._conn.close()

    async def execute(self, query: str, params: tuple = ()):
        cur = await self._conn.execute(query, params)
        await self._conn.commit()
        return cur

    async def fetchone(self, query: str, params: tuple = ()):
        cur = await self._conn.execute(query, params)
        row = await cur.fetchone()
        await cur.close()
        return row

    async def fetchall(self, query: str, params: tuple = ()):
        cur = await self._conn.execute(query, params)
        rows = await cur.fetchall()
        await cur.close()
        return rows

    # ---------- Helpers "config de guilde" utilisés partout ----------

    async def ensure_guild(self, guild_id: int):
        await self.execute(
            "INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (guild_id,)
        )
        await self.execute(
            "INSERT OR IGNORE INTO automod_settings (guild_id) VALUES (?)", (guild_id,)
        )

    async def get_guild_config(self, guild_id: int):
        cached = self._guild_config_cache.get(guild_id)
        if cached is not None:
            return cached
        await self.ensure_guild(guild_id)
        row = await self.fetchone(
            "SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)
        )
        if row is not None:
            self._guild_config_cache[guild_id] = row
        return row

    async def set_guild_config(self, guild_id: int, field: str, value):
        await self.ensure_guild(guild_id)
        await self.execute(
            f"UPDATE guild_config SET {field} = ? WHERE guild_id = ?", (value, guild_id)
        )
        # Invalide le cache : la prochaine lecture ira chercher la ligne à jour.
        self._guild_config_cache.pop(guild_id, None)

    def invalidate_guild_config(self, guild_id: int):
        """À appeler après toute modification de guild_config qui ne passe pas par
        set_guild_config (ex: /config-reset qui fait un DELETE direct)."""
        self._guild_config_cache.pop(guild_id, None)

    async def get_automod(self, guild_id: int):
        await self.ensure_guild(guild_id)
        return await self.fetchone(
            "SELECT * FROM automod_settings WHERE guild_id = ?", (guild_id,)
        )

    async def set_automod(self, guild_id: int, field: str, value: int):
        await self.ensure_guild(guild_id)
        await self.execute(
            f"UPDATE automod_settings SET {field} = ? WHERE guild_id = ?",
            (value, guild_id),
        )

    # ---------- Historique AutoMod (audit + statistiques) ----------

    async def log_automod_action(self, guild_id: int, user_id: int | None, filter_name: str, action: str, reason: str):
        await self.execute(
            "INSERT INTO automod_logs (guild_id, user_id, filter_name, action, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, filter_name, action, reason, now()),
        )

    async def automod_stats_since(self, guild_id: int, since_ts: int):
        """Nombre de déclenchements par filtre, pour /automod-status."""
        return await self.fetchall(
            "SELECT filter_name, COUNT(*) as c FROM automod_logs WHERE guild_id = ? AND timestamp >= ? "
            "GROUP BY filter_name ORDER BY c DESC",
            (guild_id, since_ts),
        )

    async def automod_history_for_user(self, guild_id: int, user_id: int, limit: int = 10):
        return await self.fetchall(
            "SELECT * FROM automod_logs WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (guild_id, user_id, limit),
        )

    async def automod_recent(self, guild_id: int, limit: int = 10):
        return await self.fetchall(
            "SELECT * FROM automod_logs WHERE guild_id = ? ORDER BY timestamp DESC LIMIT ?",
            (guild_id, limit),
        )

    async def automod_infraction_count_since(self, guild_id: int, user_id: int, since_ts: int) -> int:
        row = await self.fetchone(
            "SELECT COUNT(*) c FROM automod_logs WHERE guild_id = ? AND user_id = ? AND timestamp >= ?",
            (guild_id, user_id, since_ts),
        )
        return row["c"] if row else 0

    # ---------- Rôles exemptés d'AutoMod (staff qui ne doit jamais être filtré) ----------

    async def add_automod_exempt_role(self, guild_id: int, role_id: int):
        await self.execute(
            "INSERT OR IGNORE INTO automod_exempt_roles (guild_id, role_id) VALUES (?, ?)", (guild_id, role_id)
        )

    async def remove_automod_exempt_role(self, guild_id: int, role_id: int):
        await self.execute(
            "DELETE FROM automod_exempt_roles WHERE guild_id = ? AND role_id = ?", (guild_id, role_id)
        )

    async def list_automod_exempt_roles(self, guild_id: int):
        return await self.fetchall("SELECT role_id FROM automod_exempt_roles WHERE guild_id = ?", (guild_id,))

    # ---------- Gestionnaires du bot (membres autorisés à le configurer) ----------

    async def add_bot_manager(self, guild_id: int, user_id: int, added_by: int):
        await self.execute(
            "INSERT OR IGNORE INTO bot_managers (guild_id, user_id, added_by, added_at) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, added_by, now()),
        )

    async def remove_bot_manager(self, guild_id: int, user_id: int):
        await self.execute(
            "DELETE FROM bot_managers WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )

    async def is_bot_manager(self, guild_id: int, user_id: int) -> bool:
        row = await self.fetchone(
            "SELECT 1 FROM bot_managers WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        return row is not None

    async def list_bot_managers(self, guild_id: int):
        return await self.fetchall(
            "SELECT user_id FROM bot_managers WHERE guild_id = ?", (guild_id,)
        )

    # ---------- Liste noire GLOBALE d'utilisation du bot (toutes commandes, tous serveurs) ----------
    # Différente de "blacklist_users" (utils/automod.py) qui ne bloque que le contenu sur UN serveur :
    # ici, un utilisateur blacklisté ne peut plus utiliser AUCUNE commande du bot, nulle part.

    async def blacklist_add(self, user_id: int, reason: str, by_id: int):
        await self.execute(
            "INSERT INTO command_blacklist (user_id, reason, blacklisted_by, blacklisted_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET reason = excluded.reason, blacklisted_by = excluded.blacklisted_by, blacklisted_at = excluded.blacklisted_at",
            (user_id, reason, by_id, now()),
        )

    async def blacklist_remove(self, user_id: int):
        await self.execute("DELETE FROM command_blacklist WHERE user_id = ?", (user_id,))

    async def blacklist_get(self, user_id: int):
        return await self.fetchone("SELECT * FROM command_blacklist WHERE user_id = ?", (user_id,))

    async def blacklist_list(self):
        return await self.fetchall("SELECT * FROM command_blacklist ORDER BY blacklisted_at DESC")

    # ---------- Réglages globaux du bot (footer, couleur, présence rotative...) ----------

    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = await self.fetchone("SELECT value FROM bot_settings WHERE key = ?", (key,))
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str):
        await self.execute(
            "INSERT INTO bot_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # ---------- Alias de commandes (préfixe uniquement, par serveur) ----------

    async def add_alias(self, guild_id: int, alias: str, command_name: str):
        await self.execute(
            "INSERT INTO command_aliases (guild_id, alias, command_name) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, alias) DO UPDATE SET command_name = excluded.command_name",
            (guild_id, alias, command_name),
        )

    async def remove_alias(self, guild_id: int, alias: str):
        await self.execute("DELETE FROM command_aliases WHERE guild_id = ? AND alias = ?", (guild_id, alias))

    async def get_alias(self, guild_id: int, alias: str):
        return await self.fetchone(
            "SELECT command_name FROM command_aliases WHERE guild_id = ? AND alias = ?", (guild_id, alias)
        )

    async def list_aliases(self, guild_id: int):
        return await self.fetchall("SELECT alias, command_name FROM command_aliases WHERE guild_id = ?", (guild_id,))

    # ---------- Suivi des invitations ----------

    async def record_invite_join(self, guild_id: int, member_id: int, inviter_id: int | None, invite_code: str | None):
        await self.execute(
            "INSERT INTO member_invites (guild_id, member_id, inviter_id, invite_code, joined_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, member_id, inviter_id, invite_code, now()),
        )

    async def mark_invite_left(self, guild_id: int, member_id: int):
        await self.execute(
            "UPDATE member_invites SET left_at = ? WHERE guild_id = ? AND member_id = ? AND left_at IS NULL",
            (now(), guild_id, member_id),
        )

    async def get_invite_stats(self, guild_id: int, inviter_id: int):
        total = await self.fetchone(
            "SELECT COUNT(*) as c FROM member_invites WHERE guild_id = ? AND inviter_id = ?", (guild_id, inviter_id)
        )
        left = await self.fetchone(
            "SELECT COUNT(*) as c FROM member_invites WHERE guild_id = ? AND inviter_id = ? AND left_at IS NOT NULL",
            (guild_id, inviter_id),
        )
        total_n = total["c"] if total else 0
        left_n = left["c"] if left else 0
        return {"total": total_n, "left": left_n, "active": total_n - left_n}

    async def get_invite_leaderboard(self, guild_id: int, limit: int = 10):
        return await self.fetchall(
            "SELECT inviter_id, COUNT(*) as total, "
            "SUM(CASE WHEN left_at IS NULL THEN 1 ELSE 0 END) as active "
            "FROM member_invites WHERE guild_id = ? AND inviter_id IS NOT NULL "
            "GROUP BY inviter_id ORDER BY active DESC LIMIT ?",
            (guild_id, limit),
        )

    async def get_invited_by(self, guild_id: int, member_id: int):
        return await self.fetchone(
            "SELECT * FROM member_invites WHERE guild_id = ? AND member_id = ? ORDER BY joined_at DESC LIMIT 1",
            (guild_id, member_id),
        )

    # ---------- Économie ----------

    async def ensure_economy(self, guild_id: int, user_id: int):
        await self.execute(
            "INSERT OR IGNORE INTO economy (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id),
        )

    async def get_balance(self, guild_id: int, user_id: int):
        await self.ensure_economy(guild_id, user_id)
        return await self.fetchone(
            "SELECT * FROM economy WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )

    async def add_balance(self, guild_id: int, user_id: int, amount: int):
        await self.ensure_economy(guild_id, user_id)
        await self.execute(
            "UPDATE economy SET cash = cash + ? WHERE guild_id = ? AND user_id = ?",
            (amount, guild_id, user_id),
        )

    # ---------- Niveaux ----------

    async def ensure_level(self, guild_id: int, user_id: int):
        await self.execute(
            "INSERT OR IGNORE INTO levels (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id),
        )

    async def get_level(self, guild_id: int, user_id: int):
        await self.ensure_level(guild_id, user_id)
        return await self.fetchone(
            "SELECT * FROM levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )

    # ---------- Statistiques pour le dashboard web (web/dashboard.py) ----------

    async def commands_count_since(self, since_ts: int) -> int:
        row = await self.fetchone("SELECT COUNT(*) c FROM command_logs WHERE timestamp >= ?", (since_ts,))
        return row["c"] if row else 0

    async def commands_count_total(self) -> int:
        row = await self.fetchone("SELECT COUNT(*) c FROM command_logs")
        return row["c"] if row else 0

    async def top_commands_since(self, since_ts: int, limit: int = 5):
        return await self.fetchall(
            "SELECT command_name, COUNT(*) as c FROM command_logs WHERE timestamp >= ? "
            "GROUP BY command_name ORDER BY c DESC LIMIT ?",
            (since_ts, limit),
        )

    async def commands_hourly_since(self, since_ts: int):
        """Regroupe les commandes exécutées par tranche d'une heure, pour le mini graphique
        du dashboard (les 24 dernières heures par défaut)."""
        return await self.fetchall(
            "SELECT (timestamp / 3600) * 3600 as bucket, COUNT(*) as c FROM command_logs "
            "WHERE timestamp >= ? GROUP BY bucket ORDER BY bucket ASC",
            (since_ts,),
        )


def now() -> int:
    return int(time.time())
