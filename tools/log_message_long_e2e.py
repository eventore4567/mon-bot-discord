#!/usr/bin/env python3
"""Log AutoMod : un long message supprimé s'affiche en entier (26/11/2026).

Jayden : « fait que ça affiche tout ». La carte coupait le message vers 900
caractères (« 8. … ») et renvoyait au fichier joint.

    python3 tools/log_message_long_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402


CANDIDATURE = """1.sallohinom444
2.14 et demi
3.depuis environ 1 mois
4.je suis toujours actif sauf quand il y a cours et la nuit ( de 00h00 a 16h00 js pas la , je suis la de 16h00 - 00h00 )

5.je connais assez bien vortex, pour de bonnes, mais également de mauvaises raisons... et j'ai arreté d'etre co owner d'un serv discord que g fondé a 300 membres, donc je cherche un ptit serv a gérer
6. j'adore gérer les serv discord, et en + je suis très fort pour faire des textes, des annonces, des événements etc, donc avant d'envoyer un annonce ou qlq chose comme ca, dites moi et je vais le rendre incroyable pour donner envie aux gens!!
7.très bons en orthographe et sait tout gérer parfait ( je ferait toujours tout parfait, je deteste les erreurs ) je suis calme patient et je peux gérer les situations entre membres...
8. ca peux m'arriver de m'enerver en vocal si VRAIMEEENT on m'enerve énormément, apart ca je pense que je n'en ai pas trop ( dites moi si j'en ai, c'est juste moi qui ne sait pas )
9. j'irais les voir et leurs dire de se calmer, si ils continuent ils ont un warn ou un mute, ca dépendra de la modération de votre serveur, et si ca part trop loin alors y'aura de grandes sanctions
10. je lui mettrait un warn ( ou ca dépent de comment fonctionne ce serveur )
11. amis ou pas tié un humain bg donc ta la meme sanction
12. double sanction mais je resterais calme, je trouve ca assez drole
13. je tient au courant l'owner/co owner a propos de ca, mais ce n'est pas a moi de m'occuper de ca donc juste je préviens bien EN DETAILS ce qu'il s'est passé
14. savoir gérer les serveurs discord ou au moin un minimum et pourvoir rester calme dans les situations
15.je leurs met un warn/mute et je leurs préviens qu'il y aura des sanctions plus grosses la prochaine fois
16. si c'est que la première fois, je lui dit d'arreter et espérer qu'il s'arrete, mais si il continue il sera mute et obtiendra probablement un warn
17. je lui dit qu'il a cas créer son serv lui meme et fermer sa gueule (jrigole) nan en vrai honnetement jsp
18.si je suis juste pas d'accord, j'abandonne ou au moin je lui en parle, mais si je trouve vraiment que c'est pas juste, j'en parle a un encore + haut gradé
19.c'est a vous de choisir, mais j'espere que ce sera moi car j'ai beaucoup de qualités pour améliorer le serveur, nottement le rendre + beau et + apprecié par les gens
20. oui : sur mon ancien serv discord, j'ai acheté des pubs avec des drags sab qui a fait gagné environ 200 membres, ces membres la, la plupart étaient actifs, donc j'ai fait ENORMEMENT de giveaways sab ( des giveaways 300m + et des ketupat/ketchuru etc TOUT LES JOURS plusieurs fois ) en riddle giveaway ou juste en giveaway basique ( également fast giveaway ) t j'ai vraiment crée une communauté dans ce serveur, malheuresement je pourrait pas acheter de pubs ni faire beaucoup de giveaways, mais je ramenerait une ambiance dans le serveur!

Cordialement
"""


async def main() -> int:
    from cogs import setup_v2_core as core
    from utils import log_service

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    sys.modules["cogs.automod"].INCIDENT_LOG_DELAY_SECONDS = 0.2
    await core.set_module_enabled(bot, guild.id, "logs", True, actor_id=h.ADMIN_ID)
    await log_service.set_log_channel(bot, guild.id, "automod", h.LOGCID)
    await log_service.set_log_enabled(bot, guild.id, "automod", True)
    await bot.db.execute("INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING", (h.GID,))
    await bot.db.execute("UPDATE automod_settings SET antiinsult=1 WHERE guild_id=?", (h.GID,))
    automod = bot.get_cog("Automod")
    automod.automod_cache.clear()

    lignes = [f"{i}. voici une reponse assez longue pour la candidature numero {i}, avec des details utiles."
              for i in range(1, 26)]
    texte = "\n".join(lignes) + "\nFIN-DU-MESSAGE tu es un connard"
    message = h.build_message(bot, guild, texte, author_id=h.TARGET_ID, author_name="membre")
    debut = len(h.CALLS)
    await automod.on_message(message)
    await h.settle(idle=2.0, maximum=8)
    cartes = [js for m, p, js in h.CALLS[debut:] if m == "POST" and p == f"/channels/{h.LOGCID}/messages"]
    rendu = h.visible_text([("POST", "x", c) for c in cartes])
    check(bool(cartes), "le message offensant est journalisé", f"{len(texte)} caractères")
    check("FIN-DU-MESSAGE" in rendu and "25. voici" in rendu,
          f"la carte affiche le message en entier ({len(texte)} caractères)", rendu[-200:])
    positions = [rendu.find(f"{i}. voici") for i in range(1, 26)]
    check(all(p >= 0 for p in positions) and positions == sorted(positions)
          and all(rendu.count(f"\n{i}. voici") <= 1 for i in range(10, 26)),
          "les lignes sont dans l'ordre, sans doublon")
    check(len(rendu) <= 4000, "la carte reste sous la limite de 4000 caractères de Discord", str(len(rendu)))

    # La candidature de la capture (26/11/2026) : « fermer sa gueule (jrigole) »
    # au milieu de 2900 caractères n'est plus une « attaque adressée ».
    candidature = CANDIDATURE
    message = h.build_message(bot, guild, candidature, author_id=h.SECOND_ID, author_name="candidat")
    debut = len(h.CALLS)
    await automod.on_message(message)
    await h.settle(idle=2.0, maximum=8)
    supprime = any(m == "DELETE" and p.endswith(f"/messages/{message.id}") for m, p, _ in h.CALLS[debut:])
    check(not supprime, "la candidature avec « (jrigole) » n'est plus supprimée")

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException:
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)
