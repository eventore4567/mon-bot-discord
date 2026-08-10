"""Minimal SentriX Managed Runtime template for discord.py.

The runtime contract is intentionally explicit: application code performs all
normal setup, then waits for the platform gate before opening the Gateway.
"""

import asyncio
import os


async def wait_for_gateway_gate() -> None:
    # Production template replaces this simple file gate with the managed
    # runtime IPC client. Keeping the contract separate avoids importing user
    # modules inside the platform.
    gate = os.environ.get("SENTRIX_GATE_FILE", "/run/sentrix/gateway.ready")
    while not os.path.exists(gate):
        await asyncio.sleep(0.1)


async def main() -> None:
    await wait_for_gateway_gate()
    # import discord and construct the user's Client/Bot here.
    # token_path is the recommended tmpfs_file provider.
    token_path = os.environ.get("SENTRIX_DISCORD_TOKEN_FILE", "/run/secrets/discord_token")
    with open(token_path, "r", encoding="utf-8") as handle:
        token = handle.read().strip()
    if not token:
        raise RuntimeError("empty Discord token")
    print("SentriX managed runtime gate opened; user bot may connect")


if __name__ == "__main__":
    asyncio.run(main())
