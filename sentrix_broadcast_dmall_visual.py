"""Diffusion privée à tous les membres d'un serveur.

Une commande qui écrit à des centaines de personnes ne peut pas ressembler à une
commande ordinaire : chaque écran dit ce qui va partir, à combien de monde, et ce
qui ne peut plus être repris une fois lancé. D'où des panneaux détaillés là où un
simple « Confirmer ? » suffirait ailleurs.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from utils import sentrix_panels as panels


SEND_DELAY_SECONDS = 0.75
PROGRESS_EVERY = 25
LONGUEUR_MAX = 3500
APERCU_MAX = 1200


# ---------------------------------------------------------------------------
# Moteur de diffusion, indépendant du transport
#
# Le Dashboard doit pouvoir lancer exactement la même diffusion que +dmall sans
# passer par une interaction Discord. Le cœur est donc isolé ici : la commande
# comme le panneau web l'appellent, et il n'existe qu'UNE implémentation de
# l'envoi en masse.
# ---------------------------------------------------------------------------
@dataclass
class BilanDiffusion:
    """Compteurs d'une diffusion en cours ou terminée."""

    total: int = 0
    envoyes: int = 0
    dms_fermes: int = 0
    echecs: int = 0
    bots_ignores: int = 0
    termine: bool = False

    @property
    def traites(self) -> int:
        return self.envoyes + self.dms_fermes + self.echecs

    def en_dict(self) -> dict:
        return {
            "total": self.total,
            "envoyes": self.envoyes,
            "dms_fermes": self.dms_fermes,
            "echecs": self.echecs,
            "bots_ignores": self.bots_ignores,
            "traites": self.traites,
            "termine": self.termine,
        }


def destinataires_du_serveur(guild: discord.Guild, bot_user_id: int | None = None):
    """Membres joignables, et nombre de bots volontairement ignorés."""
    membres: list[discord.Member] = []
    bots = 0
    for membre in guild.members:
        if membre.bot:
            bots += 1
            continue
        if bot_user_id is not None and membre.id == bot_user_id:
            continue
        membres.append(membre)
    return membres, bots


async def diffuser(
    guild: discord.Guild,
    recipients: list,
    contenu: str,
    *,
    bots_ignores: int = 0,
    fabrique_panneau=None,
    progression=None,
) -> BilanDiffusion:
    """Envoie le message à chaque destinataire, sans jamais s'arrêter sur un échec.

    Un message privé fermé (``Forbidden``) est compté à part d'une vraie panne
    technique : ce n'est pas une erreur du bot, et le distinguer évite de faire
    passer une diffusion normale pour un incident.
    """
    bilan = BilanDiffusion(total=len(recipients), bots_ignores=bots_ignores)
    fabrique = fabrique_panneau or _panneau_prive_par_defaut

    for index, membre in enumerate(recipients, start=1):
        try:
            await panels.envoyer(membre, fabrique(guild, contenu))
            bilan.envoyes += 1
        except discord.Forbidden:
            bilan.dms_fermes += 1
        except Exception:
            # Un membre en échec ne doit JAMAIS interrompre les centaines d'autres.
            bilan.echecs += 1

        if index < bilan.total:
            await asyncio.sleep(SEND_DELAY_SECONDS)

        if progression is not None and (index % PROGRESS_EVERY == 0 or index == bilan.total):
            try:
                await progression(bilan)
            except Exception:
                pass  # l'affichage ne doit pas faire échouer la diffusion

    bilan.termine = True
    if progression is not None:
        try:
            await progression(bilan)
        except Exception:
            pass
    return bilan


def _panneau_prive_par_defaut(guild: discord.Guild, contenu: str) -> panels.Panneau:
    return panels.Panneau(
        titre=f"Message de {guild.name}",
        sous_titre="Annonce envoyée par l'équipe du serveur.",
        kind="brand",
        vignette=guild.icon.url if guild.icon else None,
        sections=[panels.Section("Message", texte=contenu)],
        pied=f"Message de SentriX • {guild.name}",
    )


def _duree_lisible(secondes: float) -> str:
    """Une durée qu'on lit sans calculer.

    « 412 secondes » ne dit rien à personne au moment de lancer une diffusion ;
    « environ 7 min » permet de décider tout de suite.
    """
    secondes = int(secondes)
    if secondes < 60:
        return f"environ {max(secondes, 1)} s"
    minutes = secondes // 60
    if minutes < 60:
        return f"environ {minutes} min"
    heures, reste = divmod(minutes, 60)
    return f"environ {heures} h {reste:02d}"


def _refus(titre: str, sous_titre: str, sections=()) -> panels.Panneau:
    return panels.Panneau(
        titre=titre,
        sous_titre=sous_titre,
        kind="danger",
        sections=list(sections),
        pied="Aucun message privé n'a été envoyé.",
    )


def _panneau_progression(
    titre: str,
    sous_titre: str,
    *,
    kind: str,
    traites: int,
    total: int,
    envoyes: int,
    echecs: int,
    pied: str,
) -> panels.Panneau:
    """Le même tableau de bord du début à la fin de la diffusion.

    Garder la même forme pendant et après l'envoi évite d'avoir à relire un
    écran différent au moment où le résultat compte.
    """
    return panels.Panneau(
        titre=titre,
        sous_titre=sous_titre,
        kind=kind,
        sections=[
            panels.Section(
                "Avancement",
                [
                    panels.Ligne("Traités", f"{traites} / {total}"),
                    panels.Ligne("Reçus", str(envoyes)),
                    panels.Ligne(
                        "Non délivrés",
                        str(echecs),
                        indice="messages privés fermés, blocage, ou refus de Discord",
                    ),
                ],
            )
        ],
        pied=pied,
    )


class BroadcastConfirmView(discord.ui.View):
    def __init__(
        self,
        cog: "Broadcast",
        *,
        owner_id: int,
        guild: discord.Guild,
        content: str,
        recipients: list[discord.Member],
    ) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.owner_id = owner_id
        self.guild = guild
        self.content = content
        self.recipients = recipients
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await panels.envoyer(
                interaction.response,
                _refus(
                    "Confirmation privée",
                    "Seule la personne qui a lancé la diffusion peut la confirmer.",
                ),
                ephemere=True,
            )
            return False
        return True

    def _figer(self) -> None:
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Envoyer à tous", style=discord.ButtonStyle.primary)
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.guild.id in self.cog.active_guilds:
            await panels.envoyer(
                interaction.response,
                _refus(
                    "Diffusion déjà en cours",
                    "Une autre diffusion privée tourne déjà sur ce serveur.",
                ),
                ephemere=True,
            )
            return

        self._figer()
        total = len(self.recipients)
        lancee = _panneau_progression(
            "Diffusion lancée",
            f"Envoi vers **{total} membre(s)** non-bot.",
            kind="brand",
            traites=0,
            total=total,
            envoyes=0,
            echecs=0,
            pied=f"Durée attendue : {_duree_lisible(total * SEND_DELAY_SECONDS)}.",
        )
        await interaction.response.edit_message(view=lancee, attachments=lancee.fichiers())

        self.cog.active_guilds.add(self.guild.id)
        asyncio.create_task(
            self.cog.run_broadcast(
                interaction=interaction,
                guild=self.guild,
                recipients=self.recipients,
                content=self.content,
            )
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self._figer()
        annulee = panels.Panneau(
            titre="Diffusion annulée",
            sous_titre="Aucun message privé n'a été envoyé.",
            kind="neutral",
            pied="Relance `+dmall` quand tu veux.",
        )
        await interaction.response.edit_message(view=annulee, attachments=annulee.fichiers())
        self.stop()

    async def on_timeout(self) -> None:
        self._figer()
        if self.message is None:
            return
        expiree = panels.Panneau(
            titre="Confirmation expirée",
            sous_titre="La diffusion n'a pas été lancée.",
            kind="neutral",
            pied="Deux minutes sans confirmation : la demande est abandonnée.",
        )
        try:
            await self.message.edit(view=expiree, attachments=expiree.fichiers())
        except discord.HTTPException:
            pass


class Broadcast(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.active_guilds: set[int] = set()

    async def _can_broadcast(self, ctx: commands.Context) -> bool:
        if not ctx.guild:
            return False
        if await self.bot.is_owner(ctx.author):
            return True
        return ctx.guild.owner_id == ctx.author.id

    def _panneau_prive(self, guild: discord.Guild, content: str) -> panels.Panneau:
        """Ce que le membre reçoit en message privé.

        La bannière est en HAUT du panneau, avant le texte : dans un embed,
        set_image la reléguait sous le message, donc la personne lisait une
        annonce sans savoir d'où elle venait avant d'avoir fini.
        """
        return panels.Panneau(
            titre=f"Message de {guild.name}",
            sous_titre="Annonce envoyée par l'équipe du serveur.",
            kind="brand",
            vignette=guild.icon.url if guild.icon else None,
            sections=[panels.Section("Message", texte=content)],
            pied=f"Message de SentriX • {guild.name}",
        )

    async def run_broadcast(
        self,
        *,
        interaction: discord.Interaction,
        guild: discord.Guild,
        recipients: list[discord.Member],
        content: str,
    ) -> None:
        total = len(recipients)

        async def afficher(bilan: BilanDiffusion) -> None:
            if bilan.termine:
                return
            restant = (total - bilan.traites) * SEND_DELAY_SECONDS
            encours = _panneau_progression(
                "Diffusion en cours",
                f"**{bilan.traites}** membre(s) traité(s) sur **{total}**.",
                kind="warning",
                traites=bilan.traites,
                total=total,
                envoyes=bilan.envoyes,
                echecs=bilan.dms_fermes + bilan.echecs,
                pied=f"Fin dans {_duree_lisible(restant)}.",
            )
            try:
                await interaction.edit_original_response(
                    view=encours, attachments=encours.fichiers()
                )
            except discord.HTTPException:
                pass

        try:
            # Même moteur que le panneau DM du Dashboard : une seule implémentation.
            resultat = await diffuser(
                guild,
                recipients,
                content,
                fabrique_panneau=self._panneau_prive,
                progression=afficher,
            )

            bilan = _panneau_progression(
                "Diffusion terminée",
                f"**{resultat.envoyes}** membre(s) sur **{total}** ont reçu l'annonce.",
                kind="success",
                traites=total,
                total=total,
                envoyes=resultat.envoyes,
                echecs=resultat.dms_fermes + resultat.echecs,
                pied="Un échec ne veut pas dire un blocage : la plupart"
                " viennent de messages privés fermés.",
            )
            try:
                await interaction.edit_original_response(view=bilan, attachments=bilan.fichiers())
            except discord.HTTPException:
                pass
        finally:
            self.active_guilds.discard(guild.id)

    @commands.hybrid_command(
        name="dmall",
        description="Envoie une annonce privée à tous les membres non-bot du serveur.",
    )
    @commands.guild_only()
    @app_commands.describe(message="Texte à envoyer aux membres")
    async def dmall(
        self,
        ctx: commands.Context,
        *,
        message: str,
    ) -> None:
        assert ctx.guild is not None
        ephemere = bool(ctx.interaction)

        if not await self._can_broadcast(ctx):
            await panels.envoyer(
                ctx,
                _refus(
                    "Permission refusée",
                    "Écrire à tout le serveur en privé n'est pas une action d'administration ordinaire.",
                    [
                        panels.Section(
                            "Qui peut lancer cette commande",
                            [
                                panels.Ligne("Propriétaire du serveur", "autorisé"),
                                panels.Ligne("Propriétaire de SentriX", "autorisé"),
                                panels.Ligne(
                                    "Rôle Administrateur",
                                    "**refusé**",
                                    indice="le rôle ne suffit pas pour cette commande",
                                ),
                            ],
                        )
                    ],
                ),
                ephemere=ephemere,
            )
            return

        if ctx.guild.id in self.active_guilds:
            await panels.envoyer(
                ctx,
                _refus(
                    "Diffusion déjà en cours",
                    "Attends la fin de la diffusion actuelle avant d'en lancer une autre.",
                ),
                ephemere=ephemere,
            )
            return

        content = message.strip()
        if not content:
            await panels.envoyer(
                ctx,
                _refus(
                    "Message vide",
                    "Ajoute le texte que tu veux envoyer aux membres.",
                    [panels.Section("Exemple", texte="`+dmall Maintenance ce soir à 21 h.`")],
                ),
                ephemere=ephemere,
            )
            return

        if len(content) > LONGUEUR_MAX:
            await panels.envoyer(
                ctx,
                _refus(
                    "Message trop long",
                    f"Le texte fait **{len(content)}** caractères.",
                    [
                        panels.Section(
                            "Limite",
                            [
                                panels.Ligne("Maximum", f"{LONGUEUR_MAX} caractères"),
                                panels.Ligne("À retirer", f"{len(content) - LONGUEUR_MAX} caractères"),
                            ],
                        )
                    ],
                ),
                ephemere=ephemere,
            )
            return

        recipients = [
            member
            for member in ctx.guild.members
            if not member.bot and member.id != self.bot.user.id
        ]

        if not recipients:
            await panels.envoyer(
                ctx,
                _refus(
                    "Aucun destinataire",
                    "Aucun membre non-bot n'a été trouvé sur ce serveur.",
                    [
                        panels.Section(
                            "Piste",
                            texte="Si le serveur compte pourtant des membres, il manque"
                            " probablement l'intention **Membres du serveur** à SentriX.",
                        )
                    ],
                ),
                ephemere=ephemere,
            )
            return

        apercu = content[:APERCU_MAX] + ("\n…" if len(content) > APERCU_MAX else "")
        confirmation = panels.Panneau(
            titre="Confirmer la diffusion privée",
            sous_titre=f"Le message partira à **{len(recipients)} membre(s)** non-bot.",
            kind="warning",
            sections=[
                panels.Section(
                    "Portée",
                    [
                        panels.Ligne("Destinataires", f"{len(recipients)} membre(s)"),
                        panels.Ligne("Serveur", ctx.guild.name),
                        panels.Ligne(
                            "Durée",
                            _duree_lisible(len(recipients) * SEND_DELAY_SECONDS),
                            indice="SentriX espace les envois pour respecter Discord",
                        ),
                    ],
                ),
                panels.Section("Aperçu du message", texte=apercu),
                panels.Section(
                    "À savoir avant d'envoyer",
                    [
                        panels.Ligne("Messages privés fermés", "ces membres ne recevront rien"),
                        panels.Ligne("Envoi lancé", "**il ne peut plus être annulé**"),
                    ],
                ),
            ],
            pied="Rien ne part tant que tu n'as pas confirmé.",
        )
        view = BroadcastConfirmView(
            self,
            owner_id=ctx.author.id,
            guild=ctx.guild,
            content=content,
            recipients=recipients,
        )
        sent_message = await panels.envoyer(
            ctx,
            panels.avec_composants(confirmation, view),
            ephemere=ephemere,
        )
        if isinstance(sent_message, discord.Message):
            view.message = sent_message

    @commands.command(name="dm", aliases=["mp"])
    @commands.guild_only()
    async def dm(self, ctx: commands.Context, membre: discord.Member, *, message: str) -> None:
        """Écrit à UN membre en privé, avec le même habillage que +dmall.

        Volontairement en préfixe seul : le budget slash est saturé (100/100) et
        `+dm` ne mérite pas d'évincer une commande déjà exposée.
        """
        assert ctx.guild is not None

        if not await self._can_broadcast(ctx):
            await panels.envoyer(
                ctx,
                _refus(
                    "Permission refusée",
                    "Écrire au nom du serveur en privé reste réservé à ses responsables.",
                ),
            )
            return

        if membre.bot:
            await panels.envoyer(
                ctx,
                _refus("Destinataire invalide", "Les bots ne reçoivent pas de message privé."),
            )
            return

        contenu = message.strip()
        if not contenu:
            await panels.envoyer(ctx, _refus("Message vide", "Écris le texte à envoyer."))
            return
        if len(contenu) > LONGUEUR_MAX:
            await panels.envoyer(
                ctx,
                _refus(
                    "Message trop long",
                    f"Limite : **{LONGUEUR_MAX}** caractères (actuellement {len(contenu)}).",
                ),
            )
            return

        # Le moteur partagé gère déjà la distinction « MP fermé » / vraie panne.
        bilan = await diffuser(
            ctx.guild, [membre], contenu, fabrique_panneau=self._panneau_prive
        )

        if bilan.envoyes:
            titre, sous_titre, kind = (
                "Message envoyé",
                f"{membre.mention} a bien reçu le message.",
                "success",
            )
        elif bilan.dms_fermes:
            titre, sous_titre, kind = (
                "Message privé fermé",
                f"{membre.mention} n'accepte pas les messages privés de ce serveur.",
                "warning",
            )
        else:
            titre, sous_titre, kind = (
                "Envoi impossible",
                f"Discord a refusé l'envoi à {membre.mention}.",
                "danger",
            )

        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre=f"SentriX — {titre}",
                sous_titre=sous_titre,
                kind=kind,
                sections=[panels.Section("Aperçu", texte=contenu[:APERCU_MAX])],
                pied="SentriX • Message privé",
            ),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Broadcast(bot))
