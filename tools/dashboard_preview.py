"""Aperçu local du VRAI dashboard, sans Discord ni OAuth.

Démarre le bot du harnais e2e (même chaîne que la production, serveur Discord
simulé avec sa base), construit l'application aiohttp du dashboard telle que la
production la sert, ouvre une session pour l'administrateur du serveur simulé,
puis capture chaque onglet dans Chromium (bureau et mobile).

    python tools/dashboard_preview.py                # toutes les pages
    python tools/dashboard_preview.py overview logs  # quelques pages
    python tools/dashboard_preview.py --serve        # garde le serveur ouvert

Les captures vont dans reports/dashboard_preview/ (ou --out DOSSIER).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISCORD_TOKEN", "preview.fake.token")

PORT = 8765
SESSION_ID = "preview-session"
CSRF = "preview-csrf"
DESKTOP = {"width": 1440, "height": 900}
MOBILE = {"width": 390, "height": 844}


_HAUTEUR = """() => {
  const main = document.getElementById('main');
  const haut = main ? main.getBoundingClientRect().top + window.scrollY : 0;
  return Math.ceil(Math.max(document.documentElement.scrollHeight, haut + (main ? main.scrollHeight : 0)));
}"""


def _pages() -> list[str]:
    import re

    nav = (ROOT / "web" / "dashboard_ui" / "js" / "10_nav.js").read_text(encoding="utf-8")
    server = re.search(r"const NAV_SERVER = \[(.*?)\n\];", nav, re.S).group(1)
    return re.findall(r"\['([a-z]+)', '", server)


async def _seed_demo(bot, guild, harness) -> None:
    """14 jours d'activité plausibles dans la base de TEST du harnais."""
    import random

    rng = random.Random(7)
    db, now = bot.db, int(time.time())
    members = [harness.TARGET_ID, harness.ADMIN_ID] + [m.id for m in guild.members][:4]
    for day in range(14):
        base = now - day * 86400
        for _ in range(rng.randint(25, 140) + (14 - day) * 6):
            await db.execute(
                "INSERT INTO command_logs (guild_id, user_id, command_name, timestamp) VALUES (?,?,?,?)",
                (guild.id, rng.choice(members), rng.choice(["ping", "rank", "daily", "play", "help"]), base - rng.randint(0, 86000)),
            )
        for _ in range(rng.randint(0, 6)):
            await db.execute(
                "INSERT INTO automod_logs (guild_id, user_id, filter_name, action, reason, timestamp) VALUES (?,?,?,?,?,?)",
                (guild.id, harness.TARGET_ID, rng.choice(["antilink", "antispam", "antiscam"]), "delete",
                 rng.choice(["Lien non autorisé.", "Spam de messages détecté.", "Lien d'arnaque suspect."]), base - rng.randint(0, 86000)),
            )
        for _ in range(rng.randint(1, 9)):
            await db.execute(
                "INSERT INTO member_invites (guild_id, member_id, inviter_id, joined_at) VALUES (?,?,?,?)",
                (guild.id, rng.choice(members), harness.ADMIN_ID, base - rng.randint(0, 86000)),
            )
        if rng.random() < 0.5:
            await db.execute(
                "INSERT INTO sanctions (guild_id, case_number, user_id, moderator_id, action, reason, created_at) VALUES (?,?,?,?,?,?,?)",
                (guild.id, day + 1, harness.TARGET_ID, harness.ADMIN_ID, rng.choice(["warn", "timeout", "kick"]),
                 rng.choice(["Spam répété", "Insultes", "Pub non autorisée"]), base - rng.randint(0, 86000)),
            )
        if rng.random() < 0.6:
            await db.execute(
                "INSERT INTO tickets (guild_id, channel_id, user_id, status, created_at) VALUES (?,?,?,?,?)",
                (guild.id, harness.CID, rng.choice(members), rng.choice(["ouvert", "ferme"]), base - rng.randint(0, 86000)),
            )


async def _application(demo: bool = False):
    from aiohttp import web

    from tools import sentrix_e2e_harness as harness

    bot = await harness.boot(quiet=True)
    guild = await harness.setup_world(bot)
    if demo:
        await _seed_demo(bot, guild, harness)

    import web.dashboard as dashboard
    from web import dashboard_frontend_freeze_v55 as freeze

    # Le document réellement servi en production (programme unifié).
    freeze._install_unified_document(dashboard)
    app = dashboard.build_app(bot)
    admin = guild.get_member(harness.ADMIN_ID)
    app["sessions"][SESSION_ID] = {
        "user": {"id": str(harness.ADMIN_ID), "username": getattr(admin, "display_name", "Admin"), "avatar_url": None},
        "guilds": [{
            "id": str(guild.id), "name": guild.name, "icon_url": None,
            "owner": False, "access_level": "administrator",
        }],
        "csrf": CSRF,
        "expires_at": time.time() + 86400,
    }
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PORT).start()
    return guild, runner


async def _capture(guild, pages: list[str], out: pathlib.Path) -> list[str]:
    from playwright.async_api import async_playwright

    import web.dashboard as dashboard

    out.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    async with async_playwright() as pw:
        # Chromium déjà présent sur la machine : SENTRIX_PREVIEW_CHROMIUM=/chemin/chrome.
        browser = await pw.chromium.launch(executable_path=os.environ.get("SENTRIX_PREVIEW_CHROMIUM") or None)
        for label, viewport in (("desktop", DESKTOP), ("mobile", MOBILE)):
            context = await browser.new_context(viewport=viewport, device_scale_factor=1)
            await context.add_cookies([{
                "name": dashboard.SESSION_COOKIE, "value": SESSION_ID,
                "domain": "127.0.0.1", "path": "/",
            }])
            page = await context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc, errors=errors: errors.append(str(exc)))
            page.on("response", lambda r, errors=errors: errors.append(f"HTTP {r.status} {r.url}") if r.status >= 500 else None)
            for name in pages:
                errors.clear()
                await page.goto(f"http://127.0.0.1:{PORT}/app?guild={guild.id}&tab={name}")
                try:
                    # Fin du démarrage : l'écran de chargement disparaît.
                    await page.wait_for_function(
                        "() => { const s = document.getElementById('startupScreen');"
                        " return !s || s.classList.contains('hidden') || getComputedStyle(s).display === 'none'; }",
                        timeout=20000,
                    )
                except Exception:
                    problems.append(f"{label}/{name} : écran de chargement toujours affiché après 20 s")
                await page.wait_for_timeout(1500)
                # Le dashboard défile dans son conteneur <main> : on agrandit la fenêtre
                # à la hauteur du contenu pour capturer toute la page.
                hauteur = min(int(await page.evaluate(_HAUTEUR)), 12000)
                await page.set_viewport_size({"width": viewport["width"], "height": max(viewport["height"], hauteur)})
                await page.wait_for_timeout(300)
                await page.screenshot(path=str(out / f"{label}-{name}.png"), full_page=True)
                await page.set_viewport_size(viewport)
                overflow = await page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth"
                )
                if errors:
                    problems.append(f"{label}/{name} : erreur JS {errors[0][:160]}")
                if overflow > 1:
                    problems.append(f"{label}/{name} : défilement horizontal de {overflow}px")
            await context.close()
        await browser.close()
    return problems


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pages", nargs="*")
    parser.add_argument("--out", default=str(ROOT / "reports" / "dashboard_preview"))
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--demo", action="store_true", help="remplit 14 jours d'activité de test")
    args = parser.parse_args()

    guild, runner = await _application(demo=args.demo)
    if args.serve:
        print(f"Dashboard : http://127.0.0.1:{PORT}/app?guild={guild.id} (cookie {SESSION_ID})")
        await asyncio.Event().wait()
    problems = await _capture(guild, args.pages or _pages(), pathlib.Path(args.out))
    await runner.cleanup()
    for problem in problems:
        print("!!", problem)
    print(f"Captures : {args.out}")
    return 1 if problems else 0


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.stdout.flush()
    os._exit(code)
