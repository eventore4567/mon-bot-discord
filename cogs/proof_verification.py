"""Vérification automatique par preuve visuelle pour SentriX.

Flux : un administrateur configure salon/rôle/consignes, ajoute une ou plusieurs captures
exemples, puis publie un panel. Les membres envoient leurs captures dans le salon :
SentriX analyse les éléments sémantiques, ignore les différences de taille/appareil,
vérifie la réutilisation d'images et choisit entre validation automatique, preuve
insuffisante ou vérification manuelle par le staff.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, proof_service
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.proof")

STATUS_LABELS = {
    "accepted": "VALIDÉE",
    "manual_pending": "VÉRIFICATION MANUELLE",
    "rejected": "REFUSÉE",
    "insufficient": "PREUVE INSUFFISANTE",
    "reset": "RÉINITIALISÉE",
}


def _get(row, key, default=None):
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _is_image(attachment: discord.Attachment) -> bool:
    content_type = (attachment.content_type or "").lower()
    if content_type in proof_service.SUPPORTED_MIME:
        return True
    name = attachment.filename.lower()
    return name.endswith((".png", ".jpg", ".jpeg", ".webp"))


def _channel(guild: discord.Guild, channel_id) -> str:
    if not channel_id:
        return "Non configuré"
    channel = guild.get_channel(int(channel_id))
    return channel.mention if channel else f"Introuvable (`{channel_id}`)"


def _role(guild: discord.Guild, role_id) -> str:
    if not role_id:
        return "Non configuré"
    role = guild.get_role(int(role_id))
    return role.mention if role else f"Introuvable (`{role_id}`)"


async def _delete_later(message: discord.Message, delay: float = 1.5) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


async def _send_short(channel, embed: discord.Embed, *, delay: float = 10.0):
    try:
        return await panels.envoyer(channel, panels.depuis_embed(embed), delete_after=delay, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        return None


class ProofSettingsModal(discord.ui.Modal, title="Paramètres de vérification"):
    title_input = discord.ui.TextInput(label="Titre", max_length=100)
    instructions_input = discord.ui.TextInput(
        label="Ce que la preuve doit montrer", style=discord.TextStyle.paragraph, max_length=900
    )
    required_input = discord.ui.TextInput(label="Nombre d'images nécessaires (1 à 5)", max_length=1)
    pass_input = discord.ui.TextInput(label="Seuil validation auto (70 à 100)", max_length=3)
    manual_input = discord.ui.TextInput(label="Seuil vérification staff (30 à 95)", max_length=3)

    def __init__(self, owner: "ProofSetupView", settings):
        super().__init__()
        self.owner = owner
        self.title_input.default = str(_get(settings, "title", "Vérification par preuve"))[:100]
        self.instructions_input.default = str(_get(settings, "instructions", ""))[:900]
        self.required_input.default = str(_get(settings, "required_images", 1))
        self.pass_input.default = str(_get(settings, "pass_threshold", proof_service.DEFAULT_PASS_THRESHOLD))
        self.manual_input.default = str(_get(settings, "manual_threshold", proof_service.DEFAULT_MANUAL_THRESHOLD))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            required = max(1, min(proof_service.MAX_REQUIRED_IMAGES, int(str(self.required_input.value))))
            pass_threshold = max(70, min(100, int(str(self.pass_input.value))))
            manual_threshold = max(30, min(95, int(str(self.manual_input.value))))
        except ValueError:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Les seuils et le nombre d'images doivent être des nombres.")), ephemere=True)
        if manual_threshold >= pass_threshold:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Le seuil de vérification staff doit être inférieur au seuil de validation automatique.')), ephemere=True)
        await proof_service.update_settings(
            self.owner.cog.bot,
            self.owner.guild.id,
            interaction.user.id,
            title=str(self.title_input.value).strip() or "Vérification par preuve",
            instructions=str(self.instructions_input.value).strip() or "Envoyez une capture conforme aux exemples.",
            required_images=required,
            pass_threshold=pass_threshold,
            manual_threshold=manual_threshold,
        )
        await self.owner.refresh(interaction)


class SubmissionChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, owner: "ProofSetupView"):
        self.owner = owner
        super().__init__(
            placeholder="Salon où les membres envoient leurs preuves",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=0,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0].id if self.values else None
        await proof_service.update_settings(self.owner.cog.bot, self.owner.guild.id, interaction.user.id, submission_channel_id=value)
        await self.owner.refresh(interaction)


class ReviewChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, owner: "ProofSetupView"):
        self.owner = owner
        super().__init__(
            placeholder="Salon staff pour les preuves incertaines",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=0,
            max_values=1,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0].id if self.values else None
        await proof_service.update_settings(self.owner.cog.bot, self.owner.guild.id, interaction.user.id, review_channel_id=value)
        await self.owner.refresh(interaction)


class ResultRoleSelect(discord.ui.RoleSelect):
    def __init__(self, owner: "ProofSetupView"):
        self.owner = owner
        super().__init__(placeholder="Rôle donné après validation", min_values=0, max_values=1, row=2)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0].id if self.values else None
        await proof_service.update_settings(self.owner.cog.bot, self.owner.guild.id, interaction.user.id, role_id=value)
        await self.owner.refresh(interaction)


class ProofSetupView(discord.ui.View):
    def __init__(self, cog: "ProofVerification", guild: discord.Guild, author_id: int):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild = guild
        self.author_id = int(author_id)
        self._build_components()

    def _build_components(self):
        self.clear_items()
        self.add_item(SubmissionChannelSelect(self))
        self.add_item(ReviewChannelSelect(self))
        self.add_item(ResultRoleSelect(self))

        toggle = discord.ui.Button(label="Activer / Désactiver", style=discord.ButtonStyle.primary, row=3)
        settings = discord.ui.Button(label="Texte & seuils", style=discord.ButtonStyle.secondary, row=3)
        publish = discord.ui.Button(label="Publier le panel", style=discord.ButtonStyle.success, row=3)
        examples = discord.ui.Button(label="Ajouter un exemple", style=discord.ButtonStyle.secondary, row=4)
        refresh = discord.ui.Button(label="Actualiser", style=discord.ButtonStyle.secondary, row=4)
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger, row=4)

        async def toggle_callback(interaction: discord.Interaction):
            current = await proof_service.get_settings(self.cog.bot, self.guild.id)
            errors = await self.cog.configuration_errors(self.guild, current)
            if not _get(current, "enabled", 0) and errors:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Impossible d'activer le système tant que la configuration n'est pas complète.\n\n" + '\n'.join((f'- {x}' for x in errors)))), ephemere=True)
            await proof_service.update_settings(
                self.cog.bot, self.guild.id, interaction.user.id, enabled=0 if _get(current, "enabled", 0) else 1
            )
            await self.refresh(interaction)

        async def settings_callback(interaction: discord.Interaction):
            current = await proof_service.get_settings(self.cog.bot, self.guild.id)
            await interaction.response.send_modal(ProofSettingsModal(self, current))

        async def publish_callback(interaction: discord.Interaction):
            await self.cog.publish_panel(interaction, self.guild)

        async def examples_callback(interaction: discord.Interaction):
            await panels.envoyer(interaction.response, panels.depuis_embed(embeds.neutral('SentriX — Ajouter un exemple', "Joignez une capture à `+proofexample [nom]` ou utilisez `/proofexample`.\nSentriX analyse l'exemple une seule fois puis conserve sa signature sémantique et une copie compressée pour le panel.")), ephemere=True)

        async def refresh_callback(interaction: discord.Interaction):
            await self.refresh(interaction)

        async def close_callback(interaction: discord.Interaction):
            self.clear_items()
            await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(embeds.neutral('SentriX — Vérification par preuve', 'Panneau fermé.')), self))
            self.stop()

        toggle.callback = toggle_callback
        settings.callback = settings_callback
        publish.callback = publish_callback
        examples.callback = examples_callback
        refresh.callback = refresh_callback
        close.callback = close_callback
        for item in (toggle, settings, publish, examples, refresh, close):
            self.add_item(item)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Ce panneau appartient à une autre personne.')), ephemere=True)
            return False
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Permission requise : Administrateur')), ephemere=True)
            return False
        return True

    async def build_embed(self) -> discord.Embed:
        settings = await proof_service.get_settings(self.cog.bot, self.guild.id)
        references = await proof_service.list_references(self.cog.bot, self.guild.id)
        errors = await self.cog.configuration_errors(self.guild, settings)
        status = "ACTIF" if _get(settings, "enabled", 0) else "INACTIF"
        panel = embeds.brand(
            "SentriX — Vérification par preuve",
            "Configurez une validation automatique basée sur des captures de référence. Les différences de taille d'écran, appareil et zoom ne sont pas comparées pixel par pixel.",
        )
        panel.add_field(name="État", value=f"**{status}**", inline=True)
        panel.add_field(name="Exemples enregistrés", value=str(len(references)), inline=True)
        panel.add_field(
            name="Flux",
            value=f"**Preuves :** {_channel(self.guild, _get(settings, 'submission_channel_id'))}\n"
                  f"**Vérification staff :** {_channel(self.guild, _get(settings, 'review_channel_id'))}\n"
                  f"**Rôle donné :** {_role(self.guild, _get(settings, 'role_id'))}",
            inline=False,
        )
        panel.add_field(
            name="Règles d'analyse",
            value=f"**Images nécessaires :** {_get(settings, 'required_images', 1)}\n"
                  f"**Validation automatique :** {_get(settings, 'pass_threshold', 88)} %\n"
                  f"**Vérification staff à partir de :** {_get(settings, 'manual_threshold', 65)} %\n"
                  "**Anti-réutilisation :** ACTIF\n**Suppression de la preuve d'origine :** ACTIF",
            inline=False,
        )
        panel.add_field(name="Titre du panel", value=str(_get(settings, "title", "Vérification par preuve"))[:1024], inline=False)
        panel.add_field(name="Ce que la preuve doit montrer", value=str(_get(settings, "instructions", ""))[:1024], inline=False)
        if references:
            panel.add_field(
                name="Exemples",
                value="\n".join(f"`#{_get(row, 'id')}` — {_get(row, 'label', 'Exemple')}" for row in references)[:1024],
                inline=False,
            )
        if errors:
            panel.add_field(name="À corriger", value="\n".join(f"- {error}" for error in errors)[:1024], inline=False)
        panel.set_footer(text="SentriX • +proofexample pour ajouter une capture de référence")
        return panel

    async def refresh(self, interaction: discord.Interaction):
        self._build_components()
        if interaction.response.is_done():
            await panels.editer(interaction, panels.avec_composants(panels.depuis_embed(await self.build_embed()), self))
        else:
            await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(await self.build_embed()), self))


class ProofReviewView(discord.ui.View):
    """Vue persistante : l'ID de vérification est retrouvé via l'ID du message staff."""
    def __init__(self, cog: "ProofVerification"):
        super().__init__(timeout=None)
        self.cog = cog

    async def _allowed(self, interaction: discord.Interaction) -> bool:
        return isinstance(interaction.user, discord.Member) and (
            interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator
        )

    @discord.ui.button(label="Valider", style=discord.ButtonStyle.success, custom_id="sentrix:proof:approve")
    async def approve(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not await self._allowed(interaction):
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Permission requise : Gérer les rôles')), ephemere=True)
        if interaction.guild is None or interaction.message is None:
            return
        verification = await proof_service.get_verification_by_review(self.cog.bot, interaction.guild.id, interaction.message.id)
        if not verification or _get(verification, "status") != "manual_pending":
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Cette vérification n'est plus en attente.")), ephemere=True)
        settings = await proof_service.get_settings(self.cog.bot, interaction.guild.id)
        role = interaction.guild.get_role(int(_get(settings, "role_id", 0) or 0))
        member = interaction.guild.get_member(int(_get(verification, "user_id", 0) or 0))
        if member is None:
            try:
                member = await interaction.guild.fetch_member(int(_get(verification, "user_id")))
            except (discord.NotFound, discord.HTTPException):
                member = None
        error = self.cog.role_error(interaction.guild, role)
        if member is None or error:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Impossible de donner le rôle : ' + (error or "le membre n'est plus sur le serveur."))), ephemere=True)
        try:
            await member.add_roles(role, reason=f"Preuve validée manuellement par {interaction.user}")
        except discord.HTTPException:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Discord a refusé l'ajout du rôle.")), ephemere=True)
        try:
            hashes = json.loads(_get(verification, "hashes_json", "[]") or "[]")
        except Exception:
            hashes = []
        await proof_service.record_fingerprints(
            self.cog.bot, interaction.guild.id, member.id, int(_get(verification, "id")), hashes
        )
        await proof_service.finish_verification(self.cog.bot, int(_get(verification, "id")), "accepted", interaction.user.id)
        panel = interaction.message.embeds[0] if interaction.message.embeds else embeds.success("Preuve validée.")
        panel.colour = discord.Colour.green()
        panel.add_field(name="Décision staff", value=f"**VALIDÉE** par {interaction.user.mention}", inline=False)
        await panels.editer(interaction.response, panels.depuis_embed(panel))

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger, custom_id="sentrix:proof:reject")
    async def reject(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not await self._allowed(interaction):
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Permission requise : Gérer les rôles')), ephemere=True)
        if interaction.guild is None or interaction.message is None:
            return
        verification = await proof_service.get_verification_by_review(self.cog.bot, interaction.guild.id, interaction.message.id)
        if not verification or _get(verification, "status") != "manual_pending":
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Cette vérification n'est plus en attente.")), ephemere=True)
        await proof_service.finish_verification(self.cog.bot, int(_get(verification, "id")), "rejected", interaction.user.id)
        panel = interaction.message.embeds[0] if interaction.message.embeds else embeds.error("Preuve refusée.")
        panel.colour = discord.Colour.red()
        panel.add_field(name="Décision staff", value=f"**REFUSÉE** par {interaction.user.mention}", inline=False)
        await panels.editer(interaction.response, panels.depuis_embed(panel))


class ProofVerification(commands.Cog, name="ProofVerification"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.analysis_semaphore = asyncio.Semaphore(3)

    async def cog_load(self):
        await proof_service.ensure_schema(self.bot)
        self.bot.add_view(ProofReviewView(self))

    def role_error(self, guild: discord.Guild, role: discord.Role | None) -> str | None:
        if role is None:
            return "le rôle configuré n'existe plus."
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return "SentriX n'a pas la permission Gérer les rôles."
        if role >= me.top_role:
            return "le rôle à donner doit être placé sous le rôle de SentriX."
        if role.is_default() or role.managed:
            return "ce rôle ne peut pas être attribué automatiquement."
        return None

    async def configuration_errors(self, guild: discord.Guild, settings) -> list[str]:
        errors: list[str] = []
        submission = guild.get_channel(int(_get(settings, "submission_channel_id", 0) or 0))
        review = guild.get_channel(int(_get(settings, "review_channel_id", 0) or 0))
        role = guild.get_role(int(_get(settings, "role_id", 0) or 0))
        refs = await proof_service.list_references(self.bot, guild.id)
        if not isinstance(submission, (discord.TextChannel, discord.Thread)):
            errors.append("Salon de preuves non configuré ou supprimé.")
        if not isinstance(review, (discord.TextChannel, discord.Thread)):
            errors.append("Salon de vérification staff non configuré ou supprimé.")
        if not refs:
            errors.append("Ajoutez au moins une image exemple avec +proofexample.")
        role_problem = self.role_error(guild, role)
        if role_problem:
            errors.append(role_problem[0].upper() + role_problem[1:])
        me = guild.me
        if submission and me:
            perms = submission.permissions_for(me)
            if not (perms.view_channel and perms.send_messages and perms.manage_messages and perms.attach_files):
                errors.append("SentriX doit pouvoir voir, écrire, joindre des fichiers et supprimer des messages dans le salon de preuves.")
        if review and me:
            perms = review.permissions_for(me)
            if not (perms.view_channel and perms.send_messages and perms.attach_files):
                errors.append("SentriX doit pouvoir voir, écrire et joindre des fichiers dans le salon staff.")
        return errors

    async def build_public_panel(self, guild: discord.Guild) -> tuple[list[discord.Embed], list[discord.File]]:
        settings = await proof_service.get_settings(self.bot, guild.id)
        references = await proof_service.list_references(self.bot, guild.id)
        panel = embeds.brand(
            str(_get(settings, "title", "Vérification par preuve")),
            str(_get(settings, "instructions", "Envoyez une capture conforme aux exemples.")),
        )
        panel.add_field(
            name="Comment envoyer votre preuve",
            value=f"Envoyez **{_get(settings, 'required_images', 1)} image(s) dans un même message** dans {_channel(guild, _get(settings, 'submission_channel_id'))}.\n"
                  "SentriX analyse les éléments importants indépendamment de la taille d'écran, du téléphone, du PC ou du zoom.",
            inline=False,
        )
        panel.add_field(
            name="Résultat",
            value="**VALIDÉE** — le rôle est donné automatiquement.\n"
                  "**PREUVE INSUFFISANTE** — la capture est supprimée et vous pouvez réessayer.\n"
                  "**VÉRIFICATION MANUELLE** — le staff tranche si l'analyse hésite.",
            inline=False,
        )
        panel.add_field(name="Rôle obtenu", value=_role(guild, _get(settings, "role_id")), inline=False)
        panel.set_footer(text="SentriX • Les captures réutilisées peuvent être détectées automatiquement")

        files: list[discord.File] = []
        extra_embeds: list[discord.Embed] = []
        for index, row in enumerate(references[:4], start=1):
            data = proof_service.preview_bytes(_get(row, "preview_b64"))
            if not data:
                continue
            filename = f"proof-example-{index}.jpg"
            files.append(discord.File(io.BytesIO(data), filename=filename))
            example = embeds.neutral(f"Exemple {index} — {_get(row, 'label', 'Référence')}", "Capture de référence enregistrée par le serveur.")
            example.set_image(url=f"attachment://{filename}")
            extra_embeds.append(example)
        return [panel, *extra_embeds], files

    async def publish_panel(self, target, guild: discord.Guild):
        settings = await proof_service.get_settings(self.bot, guild.id)
        errors = await self.configuration_errors(guild, settings)
        if errors:
            panel = embeds.error("Le panel ne peut pas être publié.\n\n" + "\n".join(f"- {error}" for error in errors))
            if isinstance(target, discord.Interaction):
                if target.response.is_done():
                    return await panels.envoyer(target.followup, panels.depuis_embed(panel), ephemere=True)
                return await panels.envoyer(target.response, panels.depuis_embed(panel), ephemere=True)
            return await panels.envoyer(target, panels.depuis_embed(panel))
        channel = guild.get_channel(int(_get(settings, "submission_channel_id")))
        embeds_list, files = await self.build_public_panel(guild)
        try:
            message = await channel.send(embeds=embeds_list, files=files, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            panel = embeds.error("Impossible de publier le panel dans le salon configuré.")
            if isinstance(target, discord.Interaction):
                if target.response.is_done():
                    return await panels.envoyer(target.followup, panels.depuis_embed(panel), ephemere=True)
                return await panels.envoyer(target.response, panels.depuis_embed(panel), ephemere=True)
            return await panels.envoyer(target, panels.depuis_embed(panel))
        actor = getattr(target, "user", None) or getattr(target, "author", None)
        await proof_service.update_settings(self.bot, guild.id, actor.id, panel_message_id=message.id)
        panel = embeds.success(f"Panel publié dans {channel.mention}.")
        if isinstance(target, discord.Interaction):
            if target.response.is_done():
                return await panels.envoyer(target.followup, panels.depuis_embed(panel), ephemere=True)
            return await panels.envoyer(target.response, panels.depuis_embed(panel), ephemere=True)
        return await panels.envoyer(target, panels.depuis_embed(panel))

    @commands.hybrid_command(name="proofsetup", description="Configurer la vérification automatique par preuve")
    async def proofsetup(self, ctx: commands.Context):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée sur un serveur.')))
        if not isinstance(ctx.author, discord.Member) or not ctx.author.guild_permissions.administrator:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Permission requise : Administrateur')))
        await proof_service.ensure_settings(self.bot, ctx.guild.id, actor_id=ctx.author.id)
        view = ProofSetupView(self, ctx.guild, ctx.author.id)
        await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(await view.build_embed()), view))

    @commands.hybrid_command(name="proofexample", description="Ajouter une capture exemple au système de preuve")
    @app_commands.describe(image="Capture de référence", nom="Nom de l'exemple, par exemple Confirmation")
    async def proofexample(self, ctx: commands.Context, image: discord.Attachment, *, nom: str = "Exemple"):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée sur un serveur.')))
        if not isinstance(ctx.author, discord.Member) or not ctx.author.guild_permissions.administrator:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Permission requise : Administrateur')))
        if not _is_image(image) or image.size > proof_service.MAX_IMAGE_BYTES:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez une image PNG, JPG ou WEBP de 12 Mo maximum.')))
        references = await proof_service.list_references(self.bot, ctx.guild.id)
        if len(references) >= proof_service.MAX_REFERENCES:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Maximum {proof_service.MAX_REFERENCES} exemples par serveur.')))
        settings = await proof_service.get_settings(self.bot, ctx.guild.id)
        try:
            data = await image.read()
            async with self.analysis_semaphore:
                profile = await proof_service.analyze_reference(
                    data,
                    label=nom,
                    instructions=str(_get(settings, "instructions", "")),
                )
            reference_id = await proof_service.add_reference(
                self.bot, ctx.guild.id, ctx.author.id, label=nom, data=data, profile=profile
            )
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette image est invalide ou trop petite.')))
        except Exception:
            logger.exception("Impossible d'analyser l'exemple de preuve guild=%s", ctx.guild.id)
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("L'analyse de l'image exemple est momentanément indisponible.")))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Exemple `#{reference_id}` enregistré : **{nom[:80]}**.')))

    @commands.hybrid_command(name="proofexample-remove", description="Supprimer une capture exemple")
    async def proofexample_remove(self, ctx: commands.Context, reference_id: int):
        if ctx.guild is None or not isinstance(ctx.author, discord.Member) or not ctx.author.guild_permissions.administrator:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Permission requise : Administrateur')))
        await proof_service.remove_reference(self.bot, ctx.guild.id, reference_id)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Exemple `#{reference_id}` supprimé.')))

    @commands.hybrid_command(name="proofexamples", description="Lister les captures exemples enregistrées")
    async def proofexamples(self, ctx: commands.Context):
        if ctx.guild is None or not isinstance(ctx.author, discord.Member) or not ctx.author.guild_permissions.administrator:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Permission requise : Administrateur')))
        rows = await proof_service.list_references(self.bot, ctx.guild.id)
        text = "\n".join(f"`#{_get(row, 'id')}` — {_get(row, 'label', 'Exemple')}" for row in rows) or "Aucun exemple enregistré."
        await panels.envoyer(ctx, panels.depuis_embed(embeds.neutral('SentriX — Exemples de preuve', text[:4000])))

    @commands.hybrid_command(name="proofpanel", description="Publier le panel de vérification par preuve")
    async def proofpanel(self, ctx: commands.Context):
        if ctx.guild is None or not isinstance(ctx.author, discord.Member) or not ctx.author.guild_permissions.administrator:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Permission requise : Administrateur')))
        await self.publish_panel(ctx, ctx.guild)

    @commands.hybrid_command(name="proof", description="Afficher les instructions de vérification par preuve")
    async def proof(self, ctx: commands.Context):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée sur un serveur.')))
        settings = await proof_service.get_settings(self.bot, ctx.guild.id)
        if not _get(settings, "enabled", 0):
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning('La vérification par preuve est désactivée sur ce serveur.')))
        vues, files = await self.build_public_panel(ctx.guild)
        await ctx.send(embeds=vues, files=files)

    @commands.hybrid_command(name="proofstatus", description="Voir votre dernière vérification par preuve")
    async def proofstatus(self, ctx: commands.Context):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée sur un serveur.')))
        row = await proof_service.get_latest_status(self.bot, ctx.guild.id, ctx.author.id)
        if not row:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.neutral('SentriX — Statut de preuve', 'Aucune preuve envoyée pour le moment.')))
        status = STATUS_LABELS.get(str(_get(row, "status")), str(_get(row, "status")).upper())
        panel = embeds.neutral(
            "SentriX — Statut de preuve",
            f"**État :** {status}\n**Score :** {_get(row, 'score', 0)} %",
        )
        await panels.envoyer(ctx, panels.depuis_embed(panel))

    @commands.hybrid_command(name="proofreset", description="Réinitialiser la vérification d'un membre")
    @app_commands.describe(membre="Membre à réinitialiser", retirer_role="Retirer aussi le rôle obtenu")
    async def proofreset(self, ctx: commands.Context, membre: discord.Member, retirer_role: bool = False):
        if ctx.guild is None or not isinstance(ctx.author, discord.Member) or not ctx.author.guild_permissions.administrator:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Permission requise : Administrateur')))
        settings = await proof_service.get_settings(self.bot, ctx.guild.id)
        await proof_service.reset_user(self.bot, ctx.guild.id, membre.id)
        if retirer_role:
            role = ctx.guild.get_role(int(_get(settings, "role_id", 0) or 0))
            if role and role in membre.roles and not self.role_error(ctx.guild, role):
                try:
                    await membre.remove_roles(role, reason=f"Réinitialisation preuve par {ctx.author}")
                except discord.HTTPException:
                    pass
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Vérification de {membre.mention} réinitialisée.')))

    async def _analyze_attachment(self, attachment: discord.Attachment, references, instructions: str):
        data = await attachment.read()
        fingerprint = proof_service.fingerprint_image(data)
        async with self.analysis_semaphore:
            analysis = await proof_service.analyze_candidate(data, instructions=instructions, references=references)
        return data, fingerprint, analysis

    async def _queue_manual(
        self,
        message: discord.Message,
        settings,
        decision: proof_service.Decision,
        analyses: list[proof_service.CandidateAnalysis],
        blobs: list[bytes],
        hashes: list[dict[str, str]],
    ) -> bool:
        review = message.guild.get_channel(int(_get(settings, "review_channel_id", 0) or 0))
        if not isinstance(review, (discord.TextChannel, discord.Thread)):
            return False
        details = {"decision": decision.reason, "analyses": [item.to_dict() for item in analyses]}
        verification_id = await proof_service.create_verification(
            self.bot, message.guild.id, message.author.id, message.id,
            status="manual_pending", score=decision.score, details=details, hashes=hashes,
        )
        matched = []
        missing = []
        for item in analyses:
            matched.extend(item.matched[:3])
            missing.extend(item.missing[:3])
        panel = embeds.warning(
            f"**Membre :** {message.author.mention}\n**Score automatique :** {decision.score} %\n"
            f"**Décision :** {decision.reason}",
            title="SentriX — Vérification manuelle",
        )
        if matched:
            panel.add_field(name="Éléments reconnus", value="\n".join(f"- {x}" for x in matched)[:1024], inline=False)
        if missing:
            panel.add_field(name="Éléments à vérifier", value="\n".join(f"- {x}" for x in missing)[:1024], inline=False)
        panel.set_footer(text=f"SentriX • Vérification #{verification_id}")
        files = [discord.File(io.BytesIO(data), filename=f"preuve-{verification_id}-{index}.jpg") for index, data in enumerate(blobs, start=1)]
        try:
            review_message = await panels.envoyer(review, panels.avec_composants(panels.depuis_embed(panel), ProofReviewView(self)), files=files, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            await proof_service.finish_verification(self.bot, verification_id, "insufficient")
            return False
        await proof_service.set_review_message(self.bot, verification_id, review_message.id)
        return True

    @commands.Cog.listener("on_message")
    async def on_proof_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        if not message.attachments:
            return
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return
        settings = await self.bot.db.fetchone(
            "SELECT * FROM proof_settings WHERE guild_id = ? AND submission_channel_id = ? AND enabled = 1",
            (message.guild.id, message.channel.id),
        )
        if not settings:
            return
        image_attachments = [attachment for attachment in message.attachments if _is_image(attachment)]
        required = max(1, min(proof_service.MAX_REQUIRED_IMAGES, int(_get(settings, "required_images", 1))))
        if len(image_attachments) < required:
            asyncio.create_task(_delete_later(message))
            await _send_short(
                message.channel,
                embeds.warning(
                    f"Cette vérification nécessite **{required} image(s) dans un même message**. Aucun rôle n'a été donné.",
                    title="SentriX — Preuve insuffisante",
                ),
            )
            return
        references = await proof_service.list_references(self.bot, message.guild.id)
        if not references:
            asyncio.create_task(_delete_later(message))
            await _send_short(
                message.channel,
                embeds.error("Aucune image exemple n'est enregistrée.", title="SentriX — Erreur de configuration"),
            )
            return
        role = message.guild.get_role(int(_get(settings, "role_id", 0) or 0))
        role_problem = self.role_error(message.guild, role)
        if role_problem:
            asyncio.create_task(_delete_later(message))
            await _send_short(
                message.channel,
                embeds.error(role_problem, title="SentriX — Erreur de configuration"),
            )
            return
        if role in getattr(message.author, "roles", ()):
            asyncio.create_task(_delete_later(message))
            await _send_short(message.channel, embeds.neutral("SentriX — Preuve", "Votre rôle est déjà validé."), delay=6)
            return

        chosen = image_attachments[:required]
        analyses: list[proof_service.CandidateAnalysis] = []
        blobs: list[bytes] = []
        hashes: list[dict[str, str]] = []
        duplicate = False
        try:
            results = await asyncio.gather(*(
                self._analyze_attachment(attachment, references, str(_get(settings, "instructions", "")))
                for attachment in chosen
            ))
            fingerprints = []
            for data, fingerprint, analysis in results:
                blobs.append(data)
                fingerprints.append(fingerprint)
                analyses.append(analysis)
                hashes.append({"sha256": fingerprint.sha256, "dhash": fingerprint.dhash})
                if await proof_service.find_duplicate(self.bot, message.guild.id, fingerprint):
                    duplicate = True
            for i, current in enumerate(fingerprints):
                for previous in fingerprints[:i]:
                    if current.sha256 == previous.sha256 or proof_service.hamming_distance(current.dhash, previous.dhash) <= 2:
                        duplicate = True
        except (ValueError, discord.HTTPException):
            asyncio.create_task(_delete_later(message))
            await _send_short(
                message.channel,
                embeds.warning("Une des images est invalide, trop petite ou trop lourde.", title="SentriX — Preuve insuffisante"),
            )
            return
        except Exception:
            logger.exception("Erreur pipeline preuve guild=%s user=%s", message.guild.id, message.author.id)
            asyncio.create_task(_delete_later(message))
            await _send_short(message.channel, embeds.error("L'analyse de la preuve est momentanément indisponible. Réessayez plus tard."))
            return

        decision = proof_service.classify(
            analyses,
            required_images=required,
            reference_count=len(references),
            pass_threshold=int(_get(settings, "pass_threshold", proof_service.DEFAULT_PASS_THRESHOLD)),
            manual_threshold=int(_get(settings, "manual_threshold", proof_service.DEFAULT_MANUAL_THRESHOLD)),
            duplicate=duplicate,
        )
        details = {"decision": decision.reason, "analyses": [item.to_dict() for item in analyses]}

        if decision.status == "accepted":
            try:
                await message.author.add_roles(role, reason="Preuve validée automatiquement par SentriX")
            except discord.HTTPException:
                queued = await self._queue_manual(
                    message,
                    settings,
                    proof_service.Decision("manual", decision.score, "Discord a refusé l'ajout automatique du rôle."),
                    analyses,
                    blobs,
                    hashes,
                )
                asyncio.create_task(_delete_later(message))
                await _send_short(
                    message.channel,
                    embeds.warning(
                        "La preuve a été transmise au staff." if queued else "Impossible de terminer la vérification.",
                        title="SentriX — Vérification manuelle",
                    ),
                )
                return
            verification_id = await proof_service.create_verification(
                self.bot, message.guild.id, message.author.id, message.id,
                status="accepted", score=decision.score, details=details, hashes=hashes,
            )
            await proof_service.record_fingerprints(self.bot, message.guild.id, message.author.id, verification_id, hashes)
            asyncio.create_task(_delete_later(message, 0.5))
            await _send_short(
                message.channel,
                embeds.success(f"Preuve validée. Le rôle {role.mention} vous a été attribué."),
                delay=8,
            )
            return

        if decision.status == "manual":
            queued = await self._queue_manual(message, settings, decision, analyses, blobs, hashes)
            asyncio.create_task(_delete_later(message, 0.5))
            if queued:
                await _send_short(
                    message.channel,
                    embeds.warning(
                        "La preuve n'est pas assez certaine pour être validée automatiquement. Le staff va la vérifier.",
                        title="SentriX — Vérification manuelle",
                    ),
                    delay=10,
                )
            else:
                await _send_short(
                    message.channel,
                    embeds.error("Le salon de vérification staff n'est pas disponible.", title="SentriX — Erreur de configuration"),
                )
            return

        await proof_service.create_verification(
            self.bot, message.guild.id, message.author.id, message.id,
            status="insufficient", score=decision.score, details=details, hashes=hashes,
        )
        asyncio.create_task(_delete_later(message, 0.5))
        await _send_short(
            message.channel,
            embeds.warning(
                f"La preuve envoyée ne contient pas assez d'éléments pour être validée.\n**Score :** {decision.score} %\nVous pouvez envoyer une nouvelle preuve conforme aux exemples.",
                title="SentriX — Preuve insuffisante",
            ),
            delay=10,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ProofVerification(bot))