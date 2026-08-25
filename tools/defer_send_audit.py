from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COGS = ROOT / "cogs"
TRANSPORT = ROOT / "cogs" / "final_interaction_policy.py"
BOOT = ROOT / "railway_boot.py"
transport_text = TRANSPORT.read_text(encoding="utf-8")
boot_text = BOOT.read_text(encoding="utf-8")


def dotted_name(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def decorator_names(node: ast.AsyncFunctionDef) -> set[str]:
    return {dotted_name(item.func if isinstance(item, ast.Call) else item) for item in node.decorator_list}


def call_names(node: ast.AsyncFunctionDef) -> list[str]:
    result: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            result.append(dotted_name(child.func))
    return result


# Conserve la visibilité sur les handlers qui utilisent defer + send. discord.py sait
# résoudre ce cycle nativement ; SentriX ne doit plus empiler un deuxième resolver global.
deferred_handlers: list[tuple[str, int, str]] = []
for path in sorted(COGS.rglob("*.py")):
    if "__pycache__" in path.parts:
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        decorators = decorator_names(node)
        if not any("command" in name for name in decorators):
            continue
        calls = call_names(node)
        if "ctx.defer" in calls and "ctx.send" in calls:
            deferred_handlers.append((str(path.relative_to(ROOT)), node.lineno, node.name))

# Contrat actuel : UNE couche possède Context.send/reply et les transports d'interaction.
assert "commands.Context.send = send" in transport_text
assert "commands.Context.reply = reply" in transport_text
assert "discord.InteractionResponse.send_message = send_message" in transport_text
assert "discord.InteractionResponse.edit_message = edit_message" in transport_text
assert "discord.Interaction.edit_original_response = edit_original_response" in transport_text
assert "discord.Webhook.send = webhook_send" in transport_text
assert "_sentrix_canonical_transport" in transport_text
assert 'bot._sentrix_command_transport_owner = "cogs.final_interaction_policy"' in transport_text

# Le vieux resolver defer/send n'est plus ajouté par le bootstrap Railway. Le support des
# réponses différées repose sur discord.py + le transport canonique, pas sur deux wrappers.
assert 'bot_main.EXTENSIONS.append("cogs.deferred_context_response_guard")' not in boot_text

print(
    "SentriX defer/send audit: OK "
    f"({len(deferred_handlers)} deferred hybrid handler(s), one canonical transport, no legacy resolver)"
)
for path, line, name in deferred_handlers:
    print(f"NATIVE {path}:{line} {name}")
