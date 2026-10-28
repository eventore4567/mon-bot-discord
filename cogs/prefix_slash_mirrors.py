"""Les racines / sans équivalent + : +logs, +role, +queue, +nowplaying.

28/10/2026 (Jayden) : « +logs » et « +role » ne répondaient rien alors que /logs
et /role existent. Chaque sous-commande relaie le message à la commande +
historique qui fait déjà le travail (+logsearch, +giverole…) : mêmes
vérifications de permission, même résultat — aucun second système.
"""
from __future__ import annotations

import asyncio
import copy
import logging

from discord.ext import commands

logger = logging.getLogger("bot.prefix-mirrors")

from utils.access_matrix import MIRROR_TARGETS

#: racine + → {sous-commande : commande + existante}, dérivé de la source unique.
MIROIRS: dict[str, dict[str, str]] = {}
#: raccourcis à un seul mot (+queue → +music queue)
RACCOURCIS: dict[str, str] = {}
for _nom, _cible in MIRROR_TARGETS.items():
    if " " in _nom:
        _racine, _sous = _nom.split(" ", 1)
        MIROIRS.setdefault(_racine, {})[_sous] = _cible
    else:
        RACCOURCIS[_nom] = _cible


async def relayer(ctx: commands.Context, cible: str, reste: str = "") -> None:
    """Rejoue le message comme « +<cible> <reste> » : la cible garde ses propres checks."""
    message = copy.copy(ctx.message)
    message.content = f"{ctx.clean_prefix}{cible} {reste}".strip()
    nouveau = await ctx.bot.get_context(message)
    if nouveau.command is None:
        return
    # Command.invoke et non bot.invoke : la garde « une réponse par message »
    # de bot.invoke avalait la réponse du relais (même identifiant de message).
    # prepare() exécute toujours les checks de la commande ET ceux du bot.
    try:
        await nouveau.command.invoke(nouveau)
    except commands.CommandError as exc:
        ctx.bot.dispatch("command_error", nouveau, exc)


def _aide(racine: str) -> str:
    return f"Sous-commandes de `+{racine}` : " + " · ".join(f"`+{racine} {sous}`" for sous in MIROIRS[racine])


def _sous_commande(racine: str, sous: str, cible: str) -> commands.Command:
    async def callback(ctx: commands.Context, *, reste: str = "") -> None:
        await relayer(ctx, cible, reste)

    callback.__name__ = f"miroir_{racine}_{sous}"
    return commands.Command(callback, name=sous, help=f"Équivalent de /{racine} {sous}.")


class PrefixSlashMirrors(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ajoutees: list[str] = []

    async def cog_load(self) -> None:
        self._installer()
        # Certaines racines (« logs ») existent encore au chargement puis sont
        # retirées par le nettoyage du catalogue : seconde passe une fois prêt.
        self._tache = asyncio.create_task(self._seconde_passe(), name="sentrix:prefix-mirrors")

    async def _seconde_passe(self) -> None:
        while not self.bot.is_ready():
            await asyncio.sleep(1)
        await asyncio.sleep(5)
        ajoutees = self._installer()
        if ajoutees:
            logger.info("Relais + ajoutés après le démarrage : %s", ", ".join(ajoutees))

    def _installer(self) -> list[str]:
        ajoutees = []
        for racine, sous_commandes in MIROIRS.items():
            if self.bot.get_command(racine) is not None:
                continue  # une vraie commande + existe : ne jamais la masquer

            async def racine_callback(ctx: commands.Context, _racine=racine) -> None:
                await ctx.send(_aide(_racine))

            racine_callback.__name__ = f"miroir_{racine}"
            groupe = commands.Group(racine_callback, name=racine, invoke_without_command=True,
                                    help=f"Équivalent + de /{racine}.")
            for sous, cible in sous_commandes.items():
                groupe.add_command(_sous_commande(racine, sous, cible))
            self.bot.add_command(groupe)
            ajoutees.append(racine)
        for nom, cible in RACCOURCIS.items():
            if self.bot.get_command(nom) is not None:
                continue

            async def raccourci(ctx: commands.Context, *, reste: str = "", _cible=cible) -> None:
                await relayer(ctx, _cible, reste)

            raccourci.__name__ = f"miroir_{nom}"
            self.bot.add_command(commands.Command(raccourci, name=nom, help=f"Raccourci de +{cible}."))
            ajoutees.append(nom)
        self._ajoutees.extend(ajoutees)
        return ajoutees

    async def cog_unload(self) -> None:
        tache = getattr(self, "_tache", None)
        if tache is not None:
            tache.cancel()
        for nom in self._ajoutees:
            self.bot.remove_command(nom)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PrefixSlashMirrors(bot))
