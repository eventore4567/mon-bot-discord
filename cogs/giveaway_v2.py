"""Giveaway V2 interactif de SentriX.

Cette couche est volontairement séparée du moteur historique ``giveaway-*`` :
``+giveaway create`` ouvre un vrai assistant sans arguments, tandis que les anciennes
commandes restent disponibles comme filet de compatibilité.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field

import discord
from discord.ext import commands, tasks

from utils import helpers
from utils import sentrix_panels as panels


SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS giveaways_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL UNIQUE,
        prize TEXT NOT NULL,
        winners_count INTEGER NOT NULL DEFAULT 1,
        end_at INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'actif',
        created_by INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        ping_role_id INTEGER,
        image_url TEXT,
        description TEXT,
        custom_condition TEXT,
        min_invites INTEGER NOT NULL DEFAULT 0,
        min_account_age_days INTEGER NOT NULL DEFAULT 0,
        min_server_age_days INTEGER NOT NULL DEFAULT 0,
        required_roles_json TEXT NOT NULL DEFAULT '[]',
        excluded_roles_json TEXT NOT NULL DEFAULT '[]',
        bonus_roles_json TEXT NOT NULL DEFAULT '{}',
        winners_json TEXT NOT NULL DEFAULT '[]'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS giveaway_entries_v2 (
        giveaway_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        PRIMARY KEY (giveaway_id, user_id)
    )
    """,
)


def _ids(raw: str | None) -> list[int]:
    try:
        return [int(x) for x in json.loads(raw or "[]")]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _bonus(raw: str | None) -> dict[int, int]:
    try:
        data = json.loads(raw or "{}")
        return {int(k): max(1, int(v)) for k, v in data.items()}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _weighted_unique(pool: list[tuple[int, int]], count: int) -> list[int]:
    remaining = list(pool)
    winners: list[int] = []
    for _ in range(min(count, len(remaining))):
        total = sum(max(1, weight) for _, weight in remaining)
        pick = random.uniform(0, total)
        cursor = 0.0
        for index, (user_id, weight) in enumerate(remaining):
            cursor += max(1, weight)
            if cursor >= pick:
                winners.append(user_id)
                remaining.pop(index)
                break
    return winners


@dataclass
class BuilderState:
    author_id: int
    guild_id: int
    prize: str | None = None
    duration_text: str | None = None
    duration_seconds: int | None = None
    winners: int = 1
    channel_id: int | None = None
    description: str | None = None
    image_url: str | None = None
    ping_role_id: int | None = None
    required_roles: list[int] = field(default_factory=list)
    excluded_roles: list[int] = field(default_factory=list)
    bonus_roles: list[int] = field(default_factory=list)
    bonus_multiplier: int = 2
    min_invites: int = 0
    min_account_age_days: int = 0
    min_server_age_days: int = 0
    custom_condition: str | None = None


class BaseModal(discord.ui.Modal, title="Giveaway — informations obligatoires"):
    prize = discord.ui.TextInput(label="Lot / récompense", placeholder="Nitro, rôle VIP, item...", max_length=180)
    duration = discord.ui.TextInput(label="Durée", placeholder="30m, 2h, 3j...", max_length=32)
    winners = discord.ui.TextInput(label="Nombre de gagnants", default="1", max_length=3)
    description = discord.ui.TextInput(label="Description (facultatif)", required=False, max_length=900, style=discord.TextStyle.paragraph)

    def __init__(self, owner: "GiveawayBuilderView"):
        super().__init__()
        self.owner = owner
        if owner.state.prize:
            self.prize.default = owner.state.prize
        if owner.state.duration_text:
            self.duration.default = owner.state.duration_text
        self.winners.default = str(owner.state.winners)
        if owner.state.description:
            self.description.default = owner.state.description

    async def on_submit(self, interaction: discord.Interaction):
        seconds = helpers.parse_duration(str(self.duration.value))
        try:
            winners = int(str(self.winners.value).strip())
        except ValueError:
            return await interaction.response.send_message("Le nombre de gagnants doit être un entier.", ephemeral=True)
        if not seconds:
            return await interaction.response.send_message("Durée invalide. Exemples : `30m`, `2h`, `3j`.", ephemeral=True)
        if not 1 <= winners <= 50:
            return await interaction.response.send_message("Choisissez entre 1 et 50 gagnants.", ephemeral=True)
        self.owner.state.prize = str(self.prize.value).strip()
        self.owner.state.duration_text = str(self.duration.value).strip()
        self.owner.state.duration_seconds = seconds
        self.owner.state.winners = winners
        self.owner.state.description = str(self.description.value).strip() or None
        await self.owner.refresh(interaction)


class ConditionsModal(discord.ui.Modal, title="Giveaway — conditions facultatives"):
    min_invites = discord.ui.TextInput(label="Invitations minimum", default="0", max_length=6)
    account_age = discord.ui.TextInput(label="Âge minimum du compte (jours)", default="0", max_length=6)
    server_age = discord.ui.TextInput(label="Présence minimum serveur (jours)", default="0", max_length=6)
    image = discord.ui.TextInput(label="URL image / GIF", required=False, max_length=500)
    custom = discord.ui.TextInput(label="Condition personnalisée (information)", required=False, max_length=500, style=discord.TextStyle.paragraph)

    def __init__(self, owner: "GiveawayBuilderView"):
        super().__init__()
        self.owner = owner
        self.min_invites.default = str(owner.state.min_invites)
        self.account_age.default = str(owner.state.min_account_age_days)
        self.server_age.default = str(owner.state.min_server_age_days)
        if owner.state.image_url:
            self.image.default = owner.state.image_url
        if owner.state.custom_condition:
            self.custom.default = owner.state.custom_condition

    async def on_submit(self, interaction: discord.Interaction):
        try:
            values = [int(str(x.value).strip() or "0") for x in (self.min_invites, self.account_age, self.server_age)]
        except ValueError:
            return await interaction.response.send_message("Les trois valeurs numériques doivent être des nombres entiers.", ephemeral=True)
        if any(value < 0 for value in values):
            return await interaction.response.send_message("Une condition minimum ne peut pas être négative.", ephemeral=True)
        image = str(self.image.value).strip() or None
        if image and not image.startswith(("https://", "http://")):
            return await interaction.response.send_message("L’image doit utiliser une URL `http://` ou `https://`.", ephemeral=True)
        self.owner.state.min_invites, self.owner.state.min_account_age_days, self.owner.state.min_server_age_days = values
        self.owner.state.image_url = image
        self.owner.state.custom_condition = str(self.custom.value).strip() or None
        await self.owner.refresh(interaction)


class BonusModal(discord.ui.Modal, title="Giveaway — multiplicateur bonus"):
    multiplier = discord.ui.TextInput(label="Multiplicateur des rôles bonus", placeholder="2", default="2", max_length=3)

    def __init__(self, role_view: "RoleSetupView"):
        super().__init__()
        self.role_view = role_view
        self.multiplier.default = str(role_view.owner.state.bonus_multiplier)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(str(self.multiplier.value).strip())
        except ValueError:
            return await interaction.response.send_message("Le multiplicateur doit être un entier.", ephemeral=True)
        if not 1 <= value <= 100:
            return await interaction.response.send_message("Choisissez un multiplicateur entre x1 et x100.", ephemeral=True)
        self.role_view.owner.state.bonus_multiplier = value
        await interaction.response.send_message(f"Multiplicateur enregistré : **x{value}**.", ephemeral=True)


class RequiredRoleSelect(discord.ui.RoleSelect):
    def __init__(self, owner: "RoleSetupView"):
        self.owner = owner
        super().__init__(placeholder="Rôles obligatoires (facultatif)", min_values=0, max_values=10, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.owner.owner.state.required_roles = [role.id for role in self.values]
        await interaction.response.send_message("Rôles obligatoires mis à jour.", ephemeral=True)


class ExcludedRoleSelect(discord.ui.RoleSelect):
    def __init__(self, owner: "RoleSetupView"):
        self.owner = owner
        super().__init__(placeholder="Rôles interdits (facultatif)", min_values=0, max_values=10, row=1)

    async def callback(self, interaction: discord.Interaction):
        self.owner.owner.state.excluded_roles = [role.id for role in self.values]
        await interaction.response.send_message("Rôles interdits mis à jour.", ephemeral=True)


class BonusRoleSelect(discord.ui.RoleSelect):
    def __init__(self, owner: "RoleSetupView"):
        self.owner = owner
        super().__init__(placeholder="Rôles avec chances bonus (facultatif)", min_values=0, max_values=10, row=2)

    async def callback(self, interaction: discord.Interaction):
        self.owner.owner.state.bonus_roles = [role.id for role in self.values]
        await interaction.response.send_message("Rôles bonus mis à jour.", ephemeral=True)


class PingRoleSelect(discord.ui.RoleSelect):
    def __init__(self, owner: "RoleSetupView"):
        self.owner = owner
        super().__init__(placeholder="Rôle à ping au lancement (facultatif)", min_values=0, max_values=1, row=3)

    async def callback(self, interaction: discord.Interaction):
        self.owner.owner.state.ping_role_id = self.values[0].id if self.values else None
        await interaction.response.send_message("Rôle à ping mis à jour.", ephemeral=True)


class RoleSetupView(discord.ui.View):
    def __init__(self, owner: "GiveawayBuilderView"):
        super().__init__(timeout=180)
        self.owner = owner
        self.add_item(RequiredRoleSelect(self))
        self.add_item(ExcludedRoleSelect(self))
        self.add_item(BonusRoleSelect(self))
        self.add_item(PingRoleSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner.state.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Multiplicateur bonus", style=discord.ButtonStyle.secondary, row=4)
    async def multiplier(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(BonusModal(self))


class DestinationSelect(discord.ui.ChannelSelect):
    def __init__(self, owner: "DestinationView"):
        self.owner = owner
        super().__init__(
            placeholder="Salon où publier le giveaway",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        self.owner.builder.state.channel_id = self.values[0].id
        await interaction.response.send_message(f"Salon choisi : {self.values[0].mention}", ephemeral=True)


class DestinationView(discord.ui.View):
    def __init__(self, builder: "GiveawayBuilderView"):
        super().__init__(timeout=180)
        self.builder = builder
        self.add_item(DestinationSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.builder.state.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True


class GiveawayBuilderView(discord.ui.View):
    def __init__(self, cog: "GiveawayV2", ctx: commands.Context):
        super().__init__(timeout=600)
        self.cog = cog
        self.bot = cog.bot
        self.ctx = ctx
        self.state = BuilderState(author_id=ctx.author.id, guild_id=ctx.guild.id)
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.state.author_id:
            await interaction.response.send_message("Ce setup appartient à une autre personne.", ephemeral=True)
            return False
        return True

    def setup_embed(self) -> discord.Embed:
        state = self.state
        guild = self.ctx.guild
        channel = guild.get_channel(state.channel_id) if state.channel_id else None
        e = discord.Embed(
            title="SentriX — Création d’un giveaway",
            description="Les 4 éléments de base sont obligatoires. Tout le reste est facultatif.",
            colour=discord.Colour.blurple(),
        )
        e.add_field(name="Lot", value=state.prize or "**À configurer**", inline=True)
        e.add_field(name="Durée", value=state.duration_text or "**À configurer**", inline=True)
        e.add_field(name="Gagnants", value=str(state.winners) if state.duration_seconds else "**À configurer**", inline=True)
        e.add_field(name="Salon", value=channel.mention if channel else "**À configurer**", inline=True)
        optional = []
        if state.required_roles: optional.append(f"{len(state.required_roles)} rôle(s) obligatoire(s)")
        if state.excluded_roles: optional.append(f"{len(state.excluded_roles)} rôle(s) interdit(s)")
        if state.bonus_roles: optional.append(f"{len(state.bonus_roles)} rôle(s) bonus x{state.bonus_multiplier}")
        if state.ping_role_id: optional.append("rôle à ping")
        if state.min_invites: optional.append(f"{state.min_invites}+ invitation(s)")
        if state.min_account_age_days: optional.append(f"compte {state.min_account_age_days}+ j")
        if state.min_server_age_days: optional.append(f"présence {state.min_server_age_days}+ j")
        if state.image_url: optional.append("image")
        if state.custom_condition: optional.append("condition personnalisée")
        e.add_field(name="Options", value=" • ".join(optional) if optional else "Aucune — c’est facultatif.", inline=False)
        e.set_footer(text="SentriX • Giveaway interactif")
        return e

    async def refresh(self, interaction: discord.Interaction):
        panneau = panels.avec_composants(panels.depuis_embed(self.setup_embed()), self)
        await panels.editer(interaction.response, panneau)

    @discord.ui.button(label="1. Lot / durée / gagnants", style=discord.ButtonStyle.primary, row=0)
    async def base(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(BaseModal(self))

    @discord.ui.button(label="2. Salon", style=discord.ButtonStyle.primary, row=0)
    async def destination(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_message("Choisissez le salon de publication.", view=DestinationView(self), ephemeral=True)

    @discord.ui.button(label="3. Rôles / ping / bonus", style=discord.ButtonStyle.secondary, row=0)
    async def roles(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_message(
            "Configurez uniquement les rôles dont vous avez besoin. Les rôles bonus utilisent le meilleur multiplicateur applicable, jamais un empilement.",
            view=RoleSetupView(self),
            ephemeral=True,
        )

    @discord.ui.button(label="4. Conditions", style=discord.ButtonStyle.secondary, row=1)
    async def conditions(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(ConditionsModal(self))

    @discord.ui.button(label="Aperçu", style=discord.ButtonStyle.secondary, row=1)
    async def preview(self, interaction: discord.Interaction, _button: discord.ui.Button):
        missing = self.cog.missing_base(self.state)
        if missing:
            return await interaction.response.send_message("Il manque : " + ", ".join(missing) + ".", ephemeral=True)
        end_at = int(time.time()) + int(self.state.duration_seconds or 0)
        await interaction.response.send_message(embed=self.cog.build_public_embed(self.ctx.guild, self.state, end_at, self.ctx.author), ephemeral=True)

    @discord.ui.button(label="Publier", style=discord.ButtonStyle.success, row=1)
    async def publish(self, interaction: discord.Interaction, _button: discord.ui.Button):
        missing = self.cog.missing_base(self.state)
        if missing:
            return await interaction.response.send_message("Impossible de publier. Il manque : " + ", ".join(missing) + ".", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            msg = await self.cog.publish(self.ctx.guild, self.state, self.ctx.author)
        except Exception as exc:
            return await interaction.followup.send(f"Publication impossible : {type(exc).__name__}: {str(exc)[:250]}", ephemeral=True)
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                panneau = panels.avec_composants(panels.depuis_embed(self.setup_embed()), self)
                await panels.editer(self.message, panneau)
            except discord.HTTPException:
                pass
        self.stop()
        await interaction.followup.send(f"Giveaway publié : {msg.jump_url}", ephemeral=True)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.danger, row=1)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        self.stop()
        panneau = panels.avec_composants(
            panels.depuis_embed(
                discord.Embed(
                    title="Création annulée",
                    description="Aucun giveaway n’a été publié.",
                    colour=discord.Colour.dark_grey(),
                )
            ),
            self,
        )
        await panels.editer(interaction.response, panneau)


class AdvancedGiveawayView(discord.ui.View):
    def __init__(self, count: int | None = None):
        super().__init__(timeout=None)
        label = "Participer" if count is None else f"Participer • {count}"
        button = discord.ui.Button(label=label, emoji="🎉", style=discord.ButtonStyle.primary, custom_id="sentrix:giveaway:v2:enter")
        button.callback = self.enter
        self.add_item(button)

    async def enter(self, interaction: discord.Interaction):
        cog: GiveawayV2 | None = interaction.client.get_cog("GiveawayV2")
        if cog is None:
            return await interaction.response.send_message("Le module giveaway redémarre. Réessayez dans quelques secondes.", ephemeral=True)
        await cog.toggle_entry(interaction)


class GiveawayV2(commands.Cog, name="GiveawayV2"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._schema_ready = False
        self.check_ends.start()

    async def cog_load(self):
        await self.ensure_schema()
        self.bot.add_view(AdvancedGiveawayView())

    def cog_unload(self):
        self.check_ends.cancel()

    async def ensure_schema(self):
        if self._schema_ready:
            return
        for statement in SCHEMA:
            await self.bot.db.execute(statement)
        self._schema_ready = True

    def missing_base(self, state: BuilderState) -> list[str]:
        missing = []
        if not state.prize: missing.append("le lot")
        if not state.duration_seconds: missing.append("la durée")
        if state.winners < 1: missing.append("le nombre de gagnants")
        if not state.channel_id: missing.append("le salon")
        return missing

    async def open_builder(self, ctx: commands.Context):
        view = GiveawayBuilderView(self, ctx)
        panneau = panels.avec_composants(panels.depuis_embed(view.setup_embed()), view)
        msg = await panels.envoyer(ctx, panneau)
        view.message = msg

    def build_public_embed(self, guild: discord.Guild, state: BuilderState, end_at: int, author) -> discord.Embed:
        e = discord.Embed(
            title="🎉 GIVEAWAY",
            description=((state.description + "\n\n") if state.description else "") + f"**Lot : {state.prize}**\n\nCliquez sur **Participer** pour entrer dans le tirage.",
            colour=discord.Colour.blurple(),
        )
        e.add_field(name="Fin", value=f"<t:{end_at}:R>\n<t:{end_at}:F>", inline=True)
        e.add_field(name="Gagnants", value=str(state.winners), inline=True)
        e.add_field(name="Organisé par", value=getattr(author, "mention", str(author)), inline=True)
        conditions = []
        if state.required_roles:
            conditions.append("Rôle(s) obligatoire(s) : " + ", ".join(f"<@&{x}>" for x in state.required_roles))
        if state.excluded_roles:
            conditions.append("Rôle(s) interdit(s) : " + ", ".join(f"<@&{x}>" for x in state.excluded_roles))
        if state.min_invites:
            conditions.append(f"Invitations créditées minimum : **{state.min_invites}**")
        if state.min_account_age_days:
            conditions.append(f"Compte Discord âgé d’au moins **{state.min_account_age_days} jour(s)**")
        if state.min_server_age_days:
            conditions.append(f"Présent sur le serveur depuis **{state.min_server_age_days} jour(s)**")
        if state.custom_condition:
            conditions.append(f"Condition indiquée par l’organisateur : {state.custom_condition}")
        if conditions:
            e.add_field(name="Conditions", value="\n".join(conditions)[:1024], inline=False)
        if state.bonus_roles:
            e.add_field(name="Chances bonus", value=", ".join(f"<@&{x}>" for x in state.bonus_roles) + f" → **x{state.bonus_multiplier}**", inline=False)
        if state.image_url:
            e.set_image(url=state.image_url)
        e.set_footer(text="SentriX • Les conditions automatiques sont revérifiées au tirage")
        return e

    async def publish(self, guild: discord.Guild, state: BuilderState, author) -> discord.Message:
        await self.ensure_schema()
        channel = guild.get_channel(int(state.channel_id or 0))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)) and getattr(channel, "send", None) is None:
            raise ValueError("salon de destination introuvable")
        end_at = int(time.time()) + int(state.duration_seconds or 0)
        embed = self.build_public_embed(guild, state, end_at, author)
        content = f"<@&{state.ping_role_id}>" if state.ping_role_id else None
        msg = await channel.send(
            content=content,
            embed=embed,
            view=AdvancedGiveawayView(0),
            allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False, replied_user=False),
        )
        bonus_map = {str(role_id): state.bonus_multiplier for role_id in state.bonus_roles}
        await self.bot.db.execute(
            "INSERT INTO giveaways_v2 (guild_id,channel_id,message_id,prize,winners_count,end_at,status,created_by,created_at,ping_role_id,image_url,description,custom_condition,min_invites,min_account_age_days,min_server_age_days,required_roles_json,excluded_roles_json,bonus_roles_json,winners_json) VALUES (?,?,?,?,?,?,'actif',?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                guild.id, channel.id, msg.id, state.prize, state.winners, end_at,
                author.id, int(time.time()), state.ping_role_id, state.image_url, state.description,
                state.custom_condition, state.min_invites, state.min_account_age_days, state.min_server_age_days,
                json.dumps(state.required_roles), json.dumps(state.excluded_roles), json.dumps(bonus_map), "[]",
            ),
        )
        return msg

    async def _eligibility(self, row, member: discord.Member) -> tuple[bool, str | None, int]:
        required = _ids(row["required_roles_json"])
        excluded = _ids(row["excluded_roles_json"])
        bonus = _bonus(row["bonus_roles_json"])
        member_roles = {role.id for role in member.roles}
        if excluded and member_roles.intersection(excluded):
            return False, "Un de vos rôles est interdit pour ce giveaway.", 1
        missing = [role_id for role_id in required if role_id not in member_roles]
        if missing:
            return False, "Il vous manque un rôle obligatoire : " + ", ".join(f"<@&{x}>" for x in missing), 1
        blacklisted = await self.bot.db.fetchone(
            "SELECT 1 FROM giveaway_blacklist WHERE guild_id=? AND user_id=?", (member.guild.id, member.id)
        )
        if blacklisted:
            return False, "Vous êtes sur la liste noire des giveaways de ce serveur.", 1
        if int(row["min_invites"] or 0):
            breakdown = await self.bot.db.get_invite_breakdown(member.guild.id, member.id)
            if int(breakdown.get("credited", 0)) < int(row["min_invites"]):
                return False, f"Il faut au moins **{row['min_invites']}** invitation(s) créditée(s).", 1
        age = (discord.utils.utcnow() - member.created_at).days
        if age < int(row["min_account_age_days"] or 0):
            return False, f"Votre compte doit avoir au moins **{row['min_account_age_days']} jour(s)**.", 1
        if int(row["min_server_age_days"] or 0):
            if member.joined_at is None:
                return False, "Impossible de vérifier votre ancienneté sur le serveur.", 1
            server_age = (discord.utils.utcnow() - member.joined_at).days
            if server_age < int(row["min_server_age_days"]):
                return False, f"Il faut être présent depuis **{row['min_server_age_days']} jour(s)**.", 1
        weight = max([bonus.get(role_id, 1) for role_id in member_roles] or [1])
        return True, None, weight

    async def toggle_entry(self, interaction: discord.Interaction):
        await self.ensure_schema()
        row = await self.bot.db.fetchone(
            "SELECT * FROM giveaways_v2 WHERE message_id=? AND status='actif'", (interaction.message.id,)
        )
        if row is None:
            return await interaction.response.send_message("Ce giveaway n’est plus actif.", ephemeral=True)
        if int(row["end_at"]) <= int(time.time()):
            return await interaction.response.send_message("Le giveaway est en cours de clôture.", ephemeral=True)
        member = interaction.user
        if not isinstance(member, discord.Member):
            return await interaction.response.send_message("Cette participation doit être faite depuis le serveur.", ephemeral=True)
        existing = await self.bot.db.fetchone(
            "SELECT 1 FROM giveaway_entries_v2 WHERE giveaway_id=? AND user_id=?", (row["id"], member.id)
        )
        if existing:
            await self.bot.db.execute("DELETE FROM giveaway_entries_v2 WHERE giveaway_id=? AND user_id=?", (row["id"], member.id))
            text = "Vous ne participez plus à ce giveaway."
        else:
            ok, reason, weight = await self._eligibility(row, member)
            if not ok:
                return await interaction.response.send_message(reason or "Vous ne remplissez pas les conditions.", ephemeral=True)
            await self.bot.db.execute("INSERT OR IGNORE INTO giveaway_entries_v2 (giveaway_id,user_id) VALUES (?,?)", (row["id"], member.id))
            text = "Participation enregistrée."
            if weight > 1:
                text += f" Votre rôle vous donne **x{weight}** chances."
            if row["custom_condition"]:
                text += " La condition personnalisée affichée par l’organisateur reste à respecter."
        count_row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM giveaway_entries_v2 WHERE giveaway_id=?", (row["id"],))
        count = int(count_row["n"] if count_row else 0)
        try:
            await interaction.message.edit(view=AdvancedGiveawayView(count))
        except discord.HTTPException:
            pass
        await interaction.response.send_message(text, ephemeral=True)

    async def _eligible_pool(self, row, guild: discord.Guild) -> list[tuple[int, int]]:
        entries = await self.bot.db.fetchall("SELECT user_id FROM giveaway_entries_v2 WHERE giveaway_id=?", (row["id"],))
        pool = []
        for entry in entries:
            member = guild.get_member(int(entry["user_id"]))
            if member is None:
                try:
                    member = await guild.fetch_member(int(entry["user_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    continue
            ok, _reason, weight = await self._eligibility(row, member)
            if ok:
                pool.append((member.id, weight))
        return pool

    async def finish(self, row, *, reroll: bool = False) -> list[int]:
        guild = self.bot.get_guild(int(row["guild_id"]))
        if guild is None:
            return []
        pool = await self._eligible_pool(row, guild)
        previous = _ids(row["winners_json"])
        if reroll and previous:
            without_previous = [(uid, weight) for uid, weight in pool if uid not in previous]
            if without_previous:
                pool = without_previous
        winners = _weighted_unique(pool, int(row["winners_count"] or 1))
        if not reroll:
            await self.bot.db.execute("UPDATE giveaways_v2 SET status='termine', winners_json=? WHERE id=?", (json.dumps(winners), row["id"]))
        else:
            await self.bot.db.execute("UPDATE giveaways_v2 SET winners_json=? WHERE id=?", (json.dumps(winners), row["id"]))
        channel = guild.get_channel(int(row["channel_id"]))
        mentions = ", ".join(f"<@{x}>" for x in winners) if winners else "Aucun participant éligible"
        if channel and getattr(channel, "send", None):
            title = "🎉 Nouveau tirage" if reroll else "🎉 Giveaway terminé"
            await channel.send(embed=discord.Embed(title=title, description=f"**{row['prize']}**\n\nGagnant(s) : {mentions}", colour=discord.Colour.blurple()))
            try:
                original = await channel.fetch_message(int(row["message_id"]))
                if original.embeds:
                    embed = original.embeds[0]
                    embed.description = (embed.description or "") + f"\n\n**Terminé — gagnant(s) :** {mentions}"
                    embed.colour = discord.Colour.dark_grey()
                    await original.edit(embed=embed, view=None)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        return winners

    async def handle_end(self, ctx: commands.Context, message_id: int) -> bool:
        row = await self.bot.db.fetchone("SELECT * FROM giveaways_v2 WHERE guild_id=? AND message_id=?", (ctx.guild.id, message_id))
        if row is None:
            return False
        if row["status"] != "actif":
            await ctx.send("Ce giveaway V2 est déjà terminé ou annulé.")
            return True
        winners = await self.finish(row)
        await ctx.send(f"Giveaway terminé. {len(winners)} gagnant(s) tiré(s).")
        return True

    async def handle_reroll(self, ctx: commands.Context, message_id: int) -> bool:
        row = await self.bot.db.fetchone("SELECT * FROM giveaways_v2 WHERE guild_id=? AND message_id=?", (ctx.guild.id, message_id))
        if row is None:
            return False
        if row["status"] != "termine":
            await ctx.send("Terminez d’abord ce giveaway avant de refaire un tirage.")
            return True
        winners = await self.finish(row, reroll=True)
        await ctx.send(f"Nouveau tirage effectué : {len(winners)} gagnant(s).")
        return True

    async def handle_cancel(self, ctx: commands.Context, message_id: int) -> bool:
        row = await self.bot.db.fetchone("SELECT * FROM giveaways_v2 WHERE guild_id=? AND message_id=?", (ctx.guild.id, message_id))
        if row is None:
            return False
        await self.bot.db.execute("UPDATE giveaways_v2 SET status='annule' WHERE id=?", (row["id"],))
        channel = ctx.guild.get_channel(int(row["channel_id"]))
        if channel:
            try:
                original = await channel.fetch_message(message_id)
                if original.embeds:
                    embed = original.embeds[0]
                    embed.description = (embed.description or "") + "\n\n**Giveaway annulé.**"
                    embed.colour = discord.Colour.dark_grey()
                    await original.edit(embed=embed, view=None)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        await ctx.send("Giveaway annulé.")
        return True

    @tasks.loop(seconds=15)
    async def check_ends(self):
        if not self._schema_ready:
            return
        rows = await self.bot.db.fetchall("SELECT * FROM giveaways_v2 WHERE status='actif' AND end_at<=?", (int(time.time()),))
        for row in rows:
            try:
                await self.finish(row)
            except Exception:
                # Le prochain passage retentera : on ne marque pas terminé avant le tirage.
                continue

    @check_ends.before_loop
    async def before_check_ends(self):
        await self.bot.wait_until_ready()
