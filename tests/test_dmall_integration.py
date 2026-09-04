"""Integration de la diffusion privee dans le demarrage reel de SentriX."""

import ast
from pathlib import Path

from utils import access_matrix as M


ROOT = Path(__file__).resolve().parents[1]


def test_dmall_extension_is_loaded_by_main():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    extensions = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "EXTENSIONS" for target in node.targets):
            extensions = ast.literal_eval(node.value)
            break

    assert extensions is not None
    assert "sentrix_broadcast_dmall_visual" in extensions


def test_dmall_is_classified_as_guild_owner_only():
    assert "dmall" in M.KNOWN_COMMANDS
    assert "dmall" in M.GUILD_OWNER_COMMANDS
    assert M.access_tier("dmall") == "guild-owner"
    assert M.help_requirement("dmall") == "Propriétaire du serveur uniquement"


def test_dmall_cog_keeps_the_required_safety_controls():
    source = (ROOT / "sentrix_broadcast_dmall_visual.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert 'name="dmall"' in source
    assert "if not member.bot" in source
    assert "active_guilds" in source
    assert "await asyncio.sleep(SEND_DELAY_SECONDS)" in source
    assert "Message de SentriX" in source
    assert "ralentie ou refusée" not in source
    assert any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "setup"
        for node in ast.walk(tree)
    )


def test_dmall_rend_le_systeme_compose():
    """La commande envoyait des embeds : elle vit hors de cogs/, donc aucune
    mesure d'execution ne la voyait. Ces assertions la tiennent dans le systeme."""
    source = (ROOT / "sentrix_broadcast_dmall_visual.py").read_text(encoding="utf-8")
    assert "sentrix_panels as panels" in source
    assert "panels.avec_composants(confirmation, view)" in source
    assert "discord.Embed(" not in source
    assert "embed=" not in source

    # Aucun envoi ne doit repartir par ctx.send : c'est par la que la commande
    # rendait ses embeds.
    arbre = ast.parse(source)
    envois = [
        n
        for n in ast.walk(arbre)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in ("send", "reply")
        and ast.unparse(n.func.value).split(".")[0] == "ctx"
    ]
    assert not envois, f"{len(envois)} envoi(s) encore hors du systeme compose"
    assert any(
        isinstance(n, ast.Call)
        and ast.unparse(n.func).endswith("panels.envoyer")
        and ast.unparse(n.args[0]) == "ctx"
        for n in ast.walk(arbre)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.args
    )


def test_chaque_edition_reattache_sa_banniere():
    """Un panneau d'une autre intention pointe vers un AUTRE nom de fichier.
    Sans attachments=, Discord garde l'ancienne piece jointe et l'image casse."""
    import re

    source = (ROOT / "sentrix_broadcast_dmall_visual.py").read_text(encoding="utf-8")
    editions = re.findall(r"edit(?:_message|_original_response|)\(\s*view=", source)
    assert editions, "aucune edition trouvee : le test ne verifie plus rien"
    assert source.count("attachments=") == len(editions), (
        f"{len(editions)} edition(s) de vue mais "
        f"{source.count('attachments=')} reattachement(s) de banniere"
    )


def test_le_message_prive_porte_la_banniere_en_haut():
    """L'envoi passe désormais par le moteur partagé avec le Dashboard, mais c'est
    toujours _panneau_prive (bannière en tête) qui construit le message reçu."""
    source = (ROOT / "sentrix_broadcast_dmall_visual.py").read_text(encoding="utf-8")
    assert "def _panneau_prive" in source
    # La commande fournit sa fabrique de panneau au moteur...
    assert "fabrique_panneau=self._panneau_prive" in source
    # ...et le moteur envoie bien ce panneau-là à chaque membre.
    assert "await panels.envoyer(membre, fabrique(guild, contenu))" in source
