"""Le ban et son option de suppression restent précédés du contrôle de la cible."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ban_validates_target_before_execution():
    source = (ROOT / "cogs/moderation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "ban")
    body = [ast.unparse(node) for node in method.body]
    validation = next(i for i, statement in enumerate(body) if "check_targetable(ctx, membre)" in statement)
    confirmation = next(i for i, statement in enumerate(body) if "_perform_ban" in statement)
    assert validation < confirmation
    assert "_BanPurgeView" not in ast.unparse(method)
    assert "supprimer_messages" in ast.unparse(method)


def test_ban_contract_tracks_live_slash_options():
    from tools.v25_quality_gate import CRITICAL_CONTRACTS
    assert CRITICAL_CONTRACTS["ban"] == ("membre", "raison", "envoyer_mp", "supprimer_messages")
