"""Un message ne change jamais de nature apres sa creation.

Discord pose le drapeau ``components_v2`` a la CREATION : un message ne en
embed ne deviendra jamais un panneau, et un panneau n'acceptera plus jamais
`embed=` ni `content=` — l'API renvoie 400. Une vue servie en panneau dont les
boutons re-editent en embed est donc cassee a l'usage, sans qu'aucun test
d'import ne le voie. C'est exactement ce qui etait arrive a la partie de
Puissance 4 et au message d'attente de l'IA.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = pathlib.Path(__file__).resolve().parent.parent


def _fichiers() -> list[str]:
    fichiers = [str(p) for p in sorted((RACINE / "cogs").glob("*.py"))]
    fichiers += [
        str(p)
        for p in sorted(RACINE.glob("*.py"))
        if p.name not in ("main.py", "conftest.py")
    ]
    return fichiers


def test_aucune_edition_incompatible_sur_un_panneau():
    resultat = subprocess.run(
        [sys.executable, str(RACINE / "tools" / "coherence_v2.py"), *_fichiers()],
        capture_output=True,
        text=True,
        cwd=str(RACINE),
        env={**os.environ, "DISCORD_TOKEN": "x"},
    )
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr


def test_un_message_ne_en_panneau_n_est_jamais_edite_en_embed():
    """Deuxieme forme du meme piege, hors des classes de vues.

    Un message de progression garde dans une variable (`msg = await
    panels.envoyer(...)`) est ne en panneau : l'editer ensuite avec un embed
    est refuse par Discord. C'est ce qui cassait +roleall, +iconsetup et la
    restauration de sauvegarde apres leur premier ecran.
    """
    resultat = subprocess.run(
        [sys.executable, str(RACINE / "tools" / "coherence_v2.py"), *_fichiers()],
        capture_output=True,
        text=True,
        cwd=str(RACINE),
        env={**os.environ, "DISCORD_TOKEN": "x"},
    )
    assert "est ne en panneau" not in resultat.stdout, resultat.stdout


def test_editer_refuse_ce_que_discord_refuse():
    from utils import sentrix_panels as panels
    import asyncio
    import discord

    class _Cible:
        def __init__(self):
            self.recu = None

        async def edit_message(self, **kw):
            self.recu = kw

    cible = _Cible()
    panneau = panels.Panneau(titre="T", kind="success")
    asyncio.run(
        panels.editer(cible, panneau, embed=discord.Embed(title="x"), content="y")
    )
    assert "embed" not in cible.recu
    assert "content" not in cible.recu
    assert cible.recu["view"] is panneau
    # La banniere est reattachee : un panneau d'une autre intention pointe vers
    # un AUTRE nom de fichier, et Discord garderait sinon l'ancienne image.
    assert [f.filename for f in cible.recu["attachments"]] == ["banner_success.webp"]
