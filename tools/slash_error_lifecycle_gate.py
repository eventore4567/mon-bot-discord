from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERROR_POLICY = ROOT / "cogs" / "command_error_policy.py"
TRANSPORT = ROOT / "cogs" / "final_interaction_policy.py"
PERMISSIONS = ROOT / "cogs" / "permission_guard.py"
HARDENING = ROOT / "cogs" / "command_hardening_v41.py"

error_text = ERROR_POLICY.read_text(encoding="utf-8")
transport_text = TRANSPORT.read_text(encoding="utf-8")
permissions_text = PERMISSIONS.read_text(encoding="utf-8")
hardening_text = HARDENING.read_text(encoding="utf-8")

for path, source in (
    (ERROR_POLICY, error_text), (TRANSPORT, transport_text),
    (PERMISSIONS, permissions_text), (HARDENING, hardening_text),
):
    ast.parse(source, filename=str(path))

# Un seul propriétaire d'erreur pour les slash.
assert "bot.tree.on_error = on_slash_error" in error_text
assert "_claim_slash_error" in error_text
assert "release_slash(interaction)" in error_text
assert "ephemeral=True" in error_text

# Le transport ne doit jamais réinstaller son propre handler d'erreur.
assert "bot.tree.on_error" not in transport_text
assert "command_ui_policy.style_kwargs" in transport_text

# Un refus de permission libère également le verrou de concurrence sans lancer un
# deuxième gestionnaire d'erreur.
assert "release_slash(interaction)" in permissions_text
assert "await _send_interaction_denial" in permissions_text

# La primitive de libération existe toujours dans le module de concurrence.
assert "def release_slash" in hardening_text

print("SentriX slash error lifecycle gate: OK (one error owner, lock release, private errors)")
