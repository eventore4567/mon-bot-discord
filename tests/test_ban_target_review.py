"""Non-regression: confirm /ban only after the targetability check."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ban_validates_target_before_confirmation():
    source = (ROOT / "cogs/moderation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "ban")
    body = [ast.unparse(node) for node in method.body]
    validation = next(i for i, statement in enumerate(body) if "check_targetable(ctx, membre)" in statement)
    confirmation = next(i for i, statement in enumerate(body) if "_BanPurgeView" in statement)
    assert validation < confirmation
    assert "Voulez-vous aussi supprimer ses anciens messages ?" in source
    assert "Combien de temps d'anciens messages voulez-vous supprimer ?" in source


def test_ban_contract_tracks_live_slash_options():
    from tools.v25_quality_gate import CRITICAL_CONTRACTS
    assert CRITICAL_CONTRACTS["ban"] == ("membre", "raison", "envoyer_mp")
