"""Pages /setup : snippets, réactions à des mots et annonces récurrentes.

Aucune commande de configuration slash, aucun listener supplémentaire.
L'accès au panneau est contrôlé par SentriXSetupV74.interaction_check ;
les modals et confirmations vérifient également l'auteur de la session.
"""
from __future__ import annotations

import re
import time

import discord

from cogs import recurring_messages, snippets, word_reactions
from cogs import setup_components_v73 as v73
from utils import sentrix_panels as panels
from utils.text_normalization import normaliser

MAX_SNIPPETS = 50
MAX_WORDS = 30
MAX_RECURRING = 20


async def feedback(interaction, text):
    await interaction.response.send_message(
        text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
    )


def owner_ok(shell, interaction):
    return int(interaction.user.id) == int(shell.author_id) and interaction.guild_id == shell.guild.id


class SnippetModal(discord.ui.Modal, title="Enregistrer un message"):
    nom = discord.ui.TextInput(
        label="Nom (sans espaces)", placeholder="annonce-staff", min_length=2, max_length=32,
    )
    texte = discord.ui.TextInput(
        label="Texte à enregistrer", style=discord.TextStyle.paragraph,
        min_length=1, max_length=1700,
    )

    def __init__(self, shell):
        super().__init__()
        self.shell = shell

    async def on_submit(self, interaction):
        if not owner_ok(self.shell, interaction):
            return await feedback(interaction, "Cette configuration ne vous appartient pas.")
        name = snippets.normal_name(self.nom.value)
        if not name:
            return await feedback(interaction, "Nom invalide. Utilisez 2 à 32 caractères sans espaces.")
        existing = await self.shell.bot.db.fetchone(
            "SELECT id FROM snippets WHERE guild_id=? AND name=?",
            (self.shell.guild.id, name),
        )
        if not existing:
            count = await self.shell.bot.db.fetchone(
                "SELECT COUNT(*) AS total FROM snippets WHERE guild_id=?",
                (self.shell.guild.id,),
            )
            if count and int(count["total"]) >= MAX_SNIPPETS:
                return await feedback(interaction, "Limite de 50 messages enregistrés atteinte.")
        await self.shell.bot.db.execute(
            "INSERT INTO snippets(guild_id,name,content,created_by,created_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(guild_id,name) DO UPDATE SET "
            "content=excluded.content,created_by=excluded.created_by,created_at=excluded.created_at",
            (self.shell.guild.id, name, self.texte.value.strip(), interaction.user.id, int(time.time())),
        )
        return await feedback(interaction, "Message enregistré. Utilisez /snippet send pour le publier.")


class WordModal(discord.ui.Modal, title="Réaction à un mot"):
    mot = discord.ui.TextInput(label="Mot exact", min_length=2, max_length=32)
    emoji = discord.ui.TextInput(label="Emoji (Unicode ou personnalisé)", max_length=80)

    def __init__(self, shell):
        super().__init__()
        self.shell = shell

    async def on_submit(self, interaction):
        if not owner_ok(self.shell, interaction):
            return await feedback(interaction, "Cette configuration ne vous appartient pas.")
        word = normaliser(self.mot.value)
        emoji = self.emoji.value.strip()
        if not word_reactions.WORD_RE.fullmatch(word):
            return await feedback(interaction, "Indiquez un seul mot de 2 à 32 caractères.")
        partial = discord.PartialEmoji.from_str(emoji)
        if not emoji or (partial.id is None and len(emoji) > 12):
            return await feedback(interaction, "Emoji invalide.")
        existing = await self.shell.bot.db.fetchone(
            "SELECT word FROM word_reactions WHERE guild_id=? AND word=?",
            (self.shell.guild.id, word),
        )
        if existing is None:
            count = await self.shell.bot.db.fetchone(
                "SELECT COUNT(*) AS total FROM word_reactions WHERE guild_id=?",
                (self.shell.guild.id,),
            )
            if count and int(count["total"]) >= MAX_WORDS:
                return await feedback(interaction, "Limite de 30 règles atteinte.")
        await self.shell.bot.db.execute(
            "INSERT INTO word_reactions(guild_id,word,emoji) VALUES(?,?,?) "
            "ON CONFLICT(guild_id,word) DO UPDATE SET emoji=excluded.emoji",
            (self.shell.guild.id, word, emoji),
        )
        word_reactions._CACHE.pop(self.shell.guild.id, None)
        return await feedback(interaction, "Réaction enregistrée. Actualisez le panneau.")


class RecurringModal(discord.ui.Modal, title="Message récurrent"):
    intervalle = discord.ui.TextInput(
        label="Fréquence (ex. 10m, 6h, 2d)", min_length=2, max_length=8,
    )
    texte = discord.ui.TextInput(
        label="Message à publier", style=discord.TextStyle.paragraph,
        min_length=1, max_length=1700,
    )

    def __init__(self, shell, channel_id):
        super().__init__()
        self.shell, self.channel_id = shell, channel_id

    async def on_submit(self, interaction):
        if not owner_ok(self.shell, interaction):
            return await feedback(interaction, "Cette configuration ne vous appartient pas.")
        seconds = recurring_messages.parse_interval(self.intervalle.value)
        if seconds is None:
            return await feedback(interaction, "Intervalle autorisé : entre 10 minutes et 30 jours.")
        channel = self.shell.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await feedback(interaction, "Ce salon n'existe plus.")
        if await recurring_messages.is_reserved_channel(self.shell.bot, channel):
            return await feedback(interaction, "Ce salon sert aux logs et ne peut pas recevoir de messages récurrents.")
        me = self.shell.guild.me
        perms = channel.permissions_for(me) if me is not None else None
        if not perms or not (perms.view_channel and perms.send_messages):
            return await feedback(interaction, "SentriX n'a pas la permission de publier dans ce salon.")
        row = await self.shell.bot.db.fetchone(
            "SELECT COUNT(*) AS total FROM recurring_messages WHERE guild_id=?",
            (self.shell.guild.id,),
        )
        if row and int(row["total"]) >= MAX_RECURRING:
            return await feedback(interaction, "Limite de 20 messages récurrents atteinte.")
        await self.shell.bot.db.execute(
            "INSERT INTO recurring_messages(guild_id,channel_id,content,every_s,next_at,enabled) "
            "VALUES(?,?,?,?,?,0)",
            (self.shell.guild.id, channel.id, self.texte.value.strip(),
             seconds, int(time.time())+seconds),
        )
        return await feedback(
            interaction, "Message créé en pause. Vous devez l'activer explicitement dans /setup.",
        )


async def _confirm_delete(shell, interaction, action, title):
    view = discord.ui.View(timeout=60)
    button = discord.ui.Button(label="Confirmer", style=discord.ButtonStyle.danger)

    async def confirm(next_interaction):
        if not owner_ok(shell, next_interaction):
            return await feedback(next_interaction, "Cette confirmation ne vous appartient pas.")
        await action()
        await next_interaction.response.edit_message(
            content="Modification enregistrée.", view=None,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    button.callback = confirm
    view.add_item(button)
    await interaction.response.send_message(
        title, ephemeral=True, view=view,
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def build_page(shell, page: str):
    db = shell.bot.db
    gid = shell.guild.id
    container = discord.ui.Container()
    v73.poser_banniere(container)
    titles = {
        "snippets": "Messages enregistrés",
        "word_reactions": "Réactions à des mots",
        "recurring_messages": "Messages récurrents",
    }
    container.add_item(discord.ui.TextDisplay(
        f"# {titles[page]}\nConfiguration du serveur **{shell.guild.name}**."
    ))
    container.add_item(discord.ui.Separator())

    if page == "snippets":
        rows = list(await db.fetchall(
            "SELECT name,content FROM snippets WHERE guild_id=? ORDER BY name LIMIT 50", (gid,),
        ))
        chosen = getattr(shell, "extra_snippet", "")
        if chosen not in [r["name"] for r in rows]:
            chosen = str(rows[0]["name"]) if rows else ""
        shell.extra_snippet = chosen
        container.add_item(discord.ui.TextDisplay(
            f"**{len(rows)}/50 messages enregistrés.**\n"
            "Enregistrez un texte ici, puis publiez-le avec /snippet send."
        ))
        if rows:
            picker = discord.ui.Select(
                placeholder="Choisir un message",
                options=[discord.SelectOption(label=str(r["name"]),value=str(r["name"]))
                         for r in rows[:25]],
            )
            async def choose(i):
                shell.extra_snippet = picker.values[0]
                await shell.refresh(i)
            picker.callback = choose
            container.add_item(discord.ui.ActionRow(picker))
            selected = next(r for r in rows if r["name"] == chosen)
            container.add_item(discord.ui.TextDisplay(
                f"**{chosen}**\n{str(selected['content'])[:1000]}"
            ))
        create = discord.ui.Button(label="Enregistrer", style=discord.ButtonStyle.primary)
        delete = discord.ui.Button(label="Supprimer", style=discord.ButtonStyle.danger,
                                   disabled=not chosen)
        async def create_click(i):
            await i.response.send_modal(SnippetModal(shell))
        async def delete_click(i):
            async def run():
                await db.execute("DELETE FROM snippets WHERE guild_id=? AND name=?", (gid,chosen))
                shell.extra_snippet = ""
            await _confirm_delete(shell,i,run,f"Supprimer le message enregistré **{chosen}** ?")
        create.callback = create_click
        delete.callback = delete_click
        container.add_item(discord.ui.ActionRow(create,delete))

    elif page == "word_reactions":
        rows = list(await db.fetchall(
            "SELECT word,emoji FROM word_reactions WHERE guild_id=? ORDER BY word LIMIT 30",
            (gid,),
        ))
        selected = getattr(shell,"extra_word","")
        words = [str(r["word"]) for r in rows]
        selected = selected if selected in words else (words[0] if words else "")
        shell.extra_word = selected
        container.add_item(discord.ui.TextDisplay(
            f"**{len(rows)}/30 règles.** Une seule réaction par message, uniquement pour les mots entiers. "
            "Aucune règle n'est active tant que vous n'en créez pas."
        ))
        if rows:
            pick = discord.ui.Select(
                placeholder="Choisir un mot",
                options=[discord.SelectOption(label=str(r["word"]),value=str(r["word"]))
                         for r in rows[:25]],
            )
            async def choose(i):
                shell.extra_word = pick.values[0]
                await shell.refresh(i)
            pick.callback = choose
            container.add_item(discord.ui.ActionRow(pick))
            item = next(r for r in rows if r["word"] == selected)
            container.add_item(discord.ui.TextDisplay(
                f"**Mot :** {selected}\n**Réaction :** {str(item['emoji'])}"
            ))
        add = discord.ui.Button(label="Ajouter / modifier",style=discord.ButtonStyle.primary)
        remove = discord.ui.Button(label="Supprimer",style=discord.ButtonStyle.danger,
                                   disabled=not selected)
        async def add_click(i):
            await i.response.send_modal(WordModal(shell))
        async def remove_click(i):
            await db.execute(
                "DELETE FROM word_reactions WHERE guild_id=? AND word=?", (gid,selected),
            )
            word_reactions._CACHE.pop(gid,None)
            shell.extra_word = ""
            await shell.refresh(i)
        add.callback = add_click
        remove.callback = remove_click
        container.add_item(discord.ui.ActionRow(add,remove))

    elif page == "recurring_messages":
        rows = list(await db.fetchall(
            "SELECT id,channel_id,content,every_s,enabled FROM recurring_messages "
            "WHERE guild_id=? ORDER BY id DESC LIMIT 20", (gid,),
        ))
        ident = int(getattr(shell,"extra_recurring_id",0))
        ids = [int(r["id"]) for r in rows]
        ident = ident if ident in ids else (ids[0] if ids else 0)
        shell.extra_recurring_id = ident
        container.add_item(discord.ui.TextDisplay(
            f"**{len(rows)}/20 publications.** Chaque nouveau message est créé **en pause**. "
            "Intervalle : de 10 minutes à 30 jours. Aucun ping ni envoi dans les logs."
        ))
        channels = discord.ui.ChannelSelect(
            placeholder="Choisir le salon de publication",
            channel_types=[discord.ChannelType.text],
            min_values=1,max_values=1,
        )
        async def channel_chosen(i):
            shell.extra_recurring_channel = channels.values[0].id
            await i.response.defer()
        channels.callback = channel_chosen
        container.add_item(discord.ui.ActionRow(channels))
        if rows:
            pick = discord.ui.Select(
                placeholder="Choisir un message existant",
                options=[discord.SelectOption(
                    label=f"Message #{r['id']}",
                    value=str(r["id"]),
                    description="Actif" if r["enabled"] else "En pause",
                ) for r in rows[:20]],
            )
            async def choose(i):
                shell.extra_recurring_id = int(pick.values[0])
                await shell.refresh(i)
            pick.callback=choose
            container.add_item(discord.ui.ActionRow(pick))
            chosen = next(r for r in rows if int(r["id"])==ident)
            container.add_item(discord.ui.TextDisplay(
                f"**Message #{ident} :** {'Activé' if chosen['enabled'] else 'En pause'}\n"
                f"**Salon :** <#{chosen['channel_id']}> · "
                f"**Fréquence :** {int(chosen['every_s'])//60} min\n"
                f"{str(chosen['content'])[:250]}"
            ))
        add = discord.ui.Button(label="Créer en pause",style=discord.ButtonStyle.primary)
        toggle = discord.ui.Button(
            label="Activer / mettre en pause",style=discord.ButtonStyle.secondary,
            disabled=not ident,
        )
        delete = discord.ui.Button(label="Supprimer",style=discord.ButtonStyle.danger,
                                  disabled=not ident)
        async def add_click(i):
            channel_id = getattr(shell,"extra_recurring_channel",None)
            if not channel_id:
                return await feedback(i,"Sélectionnez d'abord un salon.")
            await i.response.send_modal(RecurringModal(shell,channel_id))
        async def toggle_click(i):
            row = await db.fetchone(
                "SELECT id,channel_id,enabled,every_s FROM recurring_messages "
                "WHERE id=? AND guild_id=?", (ident,gid),
            )
            if row is None:
                return await feedback(i,"Ce message n'existe plus.")
            active = not bool(row["enabled"])
            if active:
                ch = shell.guild.get_channel(int(row["channel_id"]))
                if not isinstance(ch,discord.TextChannel) or await recurring_messages.is_reserved_channel(shell.bot,ch):
                    return await feedback(i,"Ce salon est indisponible ou réservé aux logs.")
            await db.execute(
                "UPDATE recurring_messages SET enabled=?,next_at=? WHERE id=? AND guild_id=?",
                (int(active),int(time.time())+int(row["every_s"]),ident,gid),
            )
            await shell.refresh(i)
        async def delete_click(i):
            async def run():
                await db.execute("DELETE FROM recurring_messages WHERE guild_id=? AND id=?", (gid,ident))
                shell.extra_recurring_id=0
            await _confirm_delete(shell,i,run,f"Supprimer définitivement le message récurrent #{ident} ?")
        add.callback=add_click
        toggle.callback=toggle_click
        delete.callback=delete_click
        container.add_item(discord.ui.ActionRow(add,toggle,delete))

    shell._add_navigation(container)
    shell.add_item(container)
