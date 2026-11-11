"""La couleur d'un domaine SentriX, à un seul endroit (11/11/2026).

« Rends tout uniforme, genre tout symétrique. »

SentriX affiche deux familles d'écrans : les cartes classiques (embeds, via
``utils/design_system``) et les panneaux Components V2 (via
``utils/sentrix_panels``). Chacune avait SA table de couleurs, et les deux ne
se parlaient pas. Mesuré avant cette correction, sur les huit domaines que les
deux familles connaissent : **huit désaccords sur huit**.

    Sécurité      carte 0x9B59B6 (violet)   panneau 0x22D3EE (cyan)
    Jeux          carte 0x00BCD4 (bleu)     panneau 0xFF8A3D (orange)
    Modération    carte 0xE74C3C            panneau 0xFF6B6B
    ...

Le même domaine changeait donc de couleur selon l'écran qui l'affichait. Ce
n'est pas un détail de goût : la couleur est ce qui dit au lecteur de quoi on
lui parle avant même qu'il lise le titre.

Les valeurs retenues sont celles des panneaux, et pas l'inverse, parce qu'elles
sont accordées aux BANNIÈRES de ``utils/log_banners`` : le liseré du conteneur
et le trait de la bannière doivent être le même trait. Changer les panneaux
pour suivre les cartes aurait désaccordé les images.

Ce module n'importe rien de lourd exprès : les deux familles peuvent le lire
sans se créer de dépendance l'une envers l'autre.
"""
from __future__ import annotations

#: Domaine -> couleur. Les clés sont les noms français des panneaux.
DOMAINES: dict[str, int] = {
    "moderation": 0xFF6B6B,
    "securite": 0x22D3EE,
    "tickets": 0x2DD4BF,
    "economie": 0xF5C542,
    "niveaux": 0xA3E635,
    "musique": 0xFF5FC8,
    "jeux": 0xFF8A3D,
    "ia": 0xA855F7,
    "configuration": 0xC084FC,
    "bienvenue": 0x34D399,
    "evenements": 0x818CF8,
    "depart": 0xFF6A3D,
}

#: Les noms anglais de design_system vers les noms français des panneaux. Un
#: domaine absent d'ici n'existe que d'un seul côté : il n'a rien à accorder.
EQUIVALENCES: dict[str, str] = {
    "moderation": "moderation",
    "security": "securite",
    "tickets": "tickets",
    "economy": "economie",
    "levels": "niveaux",
    "music": "musique",
    "games": "jeux",
    "ai": "ia",
    "giveaways": "evenements",
}


def couleur(domaine: str, defaut: int = 0x3B82F6) -> int:
    """La couleur d'un domaine, par son nom français ou anglais."""
    cle = str(domaine or "").strip().casefold()
    return DOMAINES.get(EQUIVALENCES.get(cle, cle), defaut)


__all__ = ["DOMAINES", "EQUIVALENCES", "couleur"]
