"""SentriX V97 — fiabilité des slash groupés + dashboard Tickets simplifié.

Ce correctif reste une couche tardive : il ne duplique pas la logique métier des commandes
préfixées et ne modifie pas le schéma des tickets. Il sécurise uniquement l'adaptation
Interaction -> Context et rend le centre Tickets plus lisible.
"""
from __future__ import annotations

import inspect
import logging
import types
import typing

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.view import StringView

import sentrix_v95_runtime as v95

logger = logging.getLogger("bot.v97-reliability")


def _unwrap_optional(annotation):
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        args = [item for item in typing.get_args(annotation) if item is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _is_attachment(annotation) -> bool:
    return _unwrap_optional(annotation) is discord.Attachment


def _needs_text_fallback(command: commands.Command) -> bool:
    """Retourne True quand les options natives ne peuvent pas reproduire le parseur +.

    Le bridge V95 sérialisait toutes les options puis les reparsait positionnellement. Une
    option facultative omise au milieu décalait alors toutes les suivantes. Pour ces formes,
    un unique champ ``arguments`` est moins joli mais fiable et identique à la commande +.
    Les pièces jointes sont hors flux texte et restent natives.
    """
    try:
        params = list(command.clean_params.items())
    except Exception:
        return True
    if len(params) > v95.MAX_OPTIONS:
        return True
    for _, parameter in params:
        if parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            return True

    text_params = [(name, p) for name, p in params if not _is_attachment(p.annotation)]
    for index, (_, parameter) in enumerate(text_params[:-1]):
        if not bool(getattr(parameter, "required", False)):
            return True
    return False


def _build_signature(command: commands.Command):
    try:
        params = list(command.clean_params.items())
    except Exception:
        params = []

    interaction = inspect.Parameter(
        "interaction",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        annotation=discord.Interaction,
    )
    if _needs_text_fallback(command):
        arguments = inspect.Parameter(
            "arguments",
            inspect.Parameter.KEYWORD_ONLY,
            annotation=str,
            default="",
        )
        return inspect.Signature([interaction, arguments]), False, ("arguments",)

    output = [interaction]
    names: list[str] = []
    native = True
    for raw_name, parameter in params:
        name = v95._safe_name(raw_name, fallback="option").replace("-", "_")
        if name in names:
            name = f"{name[:25]}_{len(names) + 1}"[:32]
        names.append(name)
        original_annotation = _unwrap_optional(parameter.annotation)
        annotation = v95._native_annotation(parameter.annotation)
        if annotation is str and original_annotation is not str:
            native = False
        required = bool(getattr(parameter, "required", False))
        output.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=annotation,
                default=inspect.Parameter.empty if required else None,
            )
        )
    return inspect.Signature(output), native, tuple(names)


def _attachment_values(kwargs: dict) -> list[discord.Attachment]:
    return [value for value in kwargs.values() if isinstance(value, discord.Attachment)]


async def _dispatch_legacy_error(ctx: commands.Context, command: commands.Command, exc: Exception) -> None:
    if not isinstance(exc, commands.CommandError):
        exc = commands.CommandInvokeError(exc)
    ctx.command_failed = True
    current = ctx.command if isinstance(ctx.command, commands.Command) else command
    await current.dispatch_error(ctx, exc)


async def _invoke_original(
    bot: commands.Bot,
    command: commands.Command,
    interaction: discord.Interaction,
    option_names: tuple[str, ...],
    kwargs: dict,
) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(thinking=True)

    ctx = await commands.Context.from_interaction(interaction)
    try:
        sentrix_context = getattr(__import__("main"), "SentriXContext", None)
        if sentrix_context is not None and not isinstance(ctx, sentrix_context):
            ctx.__class__ = sentrix_context
    except Exception:
        pass

    # AttachmentConverter lit ctx.message.attachments. Context.from_interaction crée un
    # message synthétique : on y réinjecte les pièces jointes choisies dans Discord.
    attachments = _attachment_values(kwargs)
    if attachments:
        try:
            ctx.message.attachments = list(attachments)
        except Exception:
            logger.debug("Impossible d'injecter les pièces jointes slash dans ctx.message", exc_info=True)

    root = command.root_parent or command
    path = str(command.qualified_name).split()[1:] if command.root_parent is not None else []
    ctx.command = root
    ctx.invoked_with = root.name
    ctx.invoked_parents = []
    ctx.invoked_subcommand = None
    ctx.subcommand_passed = None

    try:
        arguments = v95._argument_text(command, option_names, kwargs)
        source = " ".join([*path, arguments]).strip()
        ctx.view = StringView(source)
        bot.dispatch("command", ctx)
        await root.invoke(ctx)
    except Exception as exc:
        await _dispatch_legacy_error(ctx, root, exc)
    else:
        if not ctx.command_failed:
            bot.dispatch("command_completion", ctx)


def _replace_setup_slash(bot: commands.Bot) -> bool:
    """Remplace le /setup pollué par ctx/*args par un adaptateur propre et stable."""
    legacy = bot.get_command("setup")
    if legacy is None:
        return False
    tree = bot.tree
    try:
        tree.remove_command("setup", type=discord.AppCommandType.chat_input)
    except TypeError:
        tree.remove_command("setup")

    async def setup_callback(interaction: discord.Interaction, *, arguments: str = "") -> None:
        await _invoke_original(bot, legacy, interaction, ("arguments",), {"arguments": arguments})

    setup_callback.__name__ = "slash_setup_v97"
    setup_callback.__qualname__ = setup_callback.__name__
    setup_callback.__signature__ = inspect.Signature([
        inspect.Parameter("interaction", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=discord.Interaction),
        inspect.Parameter("arguments", inspect.Parameter.KEYWORD_ONLY, annotation=str, default=""),
    ])
    setup_callback.__annotations__ = {"interaction": discord.Interaction, "arguments": str}
    setup_callback._sentrix_original_command = "setup"
    setup_callback._sentrix_native_options = False
    tree.add_command(app_commands.Command(
        name="setup",
        description="Configurer SentriX sur ce serveur.",
        callback=setup_callback,
    ), override=True)
    return True


def install_slash() -> None:
    if getattr(v95, "_sentrix_v97_reliability", False):
        return
    v95._build_signature = _build_signature
    v95._invoke_original = _invoke_original

    current_prepare = v95.prepare_bot

    async def prepare_bot_v97(bot):
        mapping = await current_prepare(bot)
        if not _replace_setup_slash(bot):
            logger.warning("V97 : commande +setup introuvable, /setup non remplacé.")
        return mapping

    prepare_bot_v97._sentrix_v97 = True
    prepare_bot_v97._sentrix_original = current_prepare
    v95.prepare_bot = prepare_bot_v97
    v95._sentrix_v97_reliability = True
    logger.warning("V97 slash actif : gaps optionnels sûrs, attachments restaurés, /setup nettoyé.")


DASHBOARD_CSS = r'''
<style id="sentrix-ticket-simple-v97-css">
body.sx-ticket-v97 #fields{display:grid;grid-template-columns:1fr;gap:14px}
body.sx-ticket-v97 #sentrixTicketCenterV35{margin-top:0;gap:14px}
body.sx-ticket-v97 .sx-ticket-head{border:0;padding:0 0 4px}
body.sx-ticket-v97 .sx-ticket-head h3{font-size:20px}
body.sx-ticket-v97 .sx-ticket-head p{font-size:12px;line-height:1.5}
.sx-ticket-guide-v97{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;padding:12px;border:1px solid #2b3448;border-radius:14px;background:#0d131d}
.sx-ticket-guide-v97 span{display:flex;align-items:center;gap:8px;min-height:42px;padding:8px 10px;border:1px solid #283247;border-radius:10px;background:#111925;color:#aab4c5;font-size:10px;font-weight:800}
.sx-ticket-guide-v97 b{display:grid;place-items:center;flex:0 0 22px;height:22px;border-radius:7px;background:#6e57d2;color:white;font-size:10px}
body.sx-ticket-v97 .sx-ticket-section{border-radius:14px}
body.sx-ticket-v97 .sx-ticket-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;padding:10px}
body.sx-ticket-v97 .sx-ticket-row{grid-template-columns:1fr;gap:9px;border:1px solid #273145!important;border-radius:11px;background:#111824;padding:11px;min-height:0}
body.sx-ticket-v97 .sx-ticket-cell{display:block;white-space:normal}
body.sx-ticket-v97 .sx-ticket-actions{justify-content:flex-start}
.sx-ticket-advanced-v97{border:1px solid #273145;border-radius:12px;background:#0f151f;overflow:hidden}
.sx-ticket-advanced-v97>summary{padding:12px 13px;cursor:pointer;color:#b5becd;font-size:11px;font-weight:850;list-style:none}
.sx-ticket-advanced-v97>summary::after{content:"Afficher";float:right;color:#7f8a9d;font-size:9px}
.sx-ticket-advanced-v97[open]>summary::after{content:"Masquer"}
.sx-ticket-advanced-body-v97{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:0 12px 12px}
.sx-ticket-wizard-v97{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;padding:11px 15px;border-bottom:1px solid #252d3e;background:#0d121b}
.sx-ticket-wizard-v97 button{min-height:38px;border:1px solid #303a50;border-radius:9px;background:#131a26;color:#8f9aab;font-size:10px;font-weight:850;cursor:pointer}
.sx-ticket-wizard-v97 button.active{border-color:#745de0;background:#241d43;color:#ded5ff}
.sx-ticket-publish-v97{display:none;padding:15px;border:1px solid #2d3750;border-radius:11px;background:#111824;color:#aeb8c8;font-size:11px;line-height:1.55}
.sx-ticket-publish-v97.active{display:block}
.sx-ticket-publish-v97 b{display:block;margin-bottom:6px;color:#f0edf6;font-size:13px}
body.sx-ticket-v97 .sx-type-wrap{grid-template-columns:repeat(2,minmax(0,1fr))}
body.sx-ticket-v97 .sx-type-card{border-radius:12px;background:#101722}
@media(max-width:760px){.sx-ticket-guide-v97,.sx-ticket-wizard-v97{grid-template-columns:1fr 1fr}body.sx-ticket-v97 .sx-ticket-list,body.sx-ticket-v97 .sx-type-wrap,.sx-ticket-advanced-body-v97{grid-template-columns:1fr}}
</style>
'''

DASHBOARD_JS = r'''
<script id="sentrix-ticket-simple-v97-js">
(() => {
  "use strict";
  if (window.__sentrixTicketSimpleV97) return;
  window.__sentrixTicketSimpleV97 = true;
  let step = 1;
  const $ = id => document.getElementById(id);
  const active = () => { try { return typeof state !== "undefined" && state.tab === "tickets"; } catch (_) { return false; } };

  function advancedSettings(){
    const fields = $("fields"), center = $("sentrixTicketCenterV35");
    if (!fields || !center || $("sxTicketAdvancedV97")) return;
    const movable = [...fields.children].filter(node => node !== center && !String(node.id || "").startsWith("sentrixTicket"));
    if (!movable.length) return;
    const details = document.createElement("details");
    details.id = "sxTicketAdvancedV97";
    details.className = "sx-ticket-advanced-v97";
    details.innerHTML = '<summary>Réglages avancés du serveur</summary><div class="sx-ticket-advanced-body-v97"></div>';
    fields.insertBefore(details, center);
    const body = details.querySelector(".sx-ticket-advanced-body-v97");
    movable.forEach(node => body.appendChild(node));
  }

  function guide(){
    const center = $("sentrixTicketCenterV35");
    if (!center || center.querySelector(".sx-ticket-guide-v97")) return;
    const guide = document.createElement("div");
    guide.className = "sx-ticket-guide-v97";
    guide.innerHTML = '<span><b>1</b>Général</span><span><b>2</b>Équipe</span><span><b>3</b>Panel</span><span><b>4</b>Publication</span>';
    const head = center.querySelector(".sx-ticket-head");
    if (head) head.after(guide); else center.prepend(guide);
  }

  function applyStep(editor){
    const sections = [...editor.querySelectorAll(".sx-editor-body > .sx-editor-section")];
    if (sections.length < 4) return;
    const content = sections[0], appearance = sections[1], roles = sections[2], types = sections[3];
    const labels = ["1. Général", "3. Apparence du panel", "2. Équipe", "3. Boutons et types"];
    sections.forEach((section, index) => { const summary = section.querySelector(":scope > summary"); if (summary) summary.textContent = labels[index]; });
    content.style.display = step === 1 ? "block" : "none";
    roles.style.display = step === 2 ? "block" : "none";
    appearance.style.display = step === 3 ? "block" : "none";
    types.style.display = step === 3 ? "block" : "none";
    [content, appearance, roles, types].forEach(section => section.open = true);
    editor.querySelectorAll(".sx-ticket-wizard-v97 button").forEach(button => button.classList.toggle("active", Number(button.dataset.step) === step));
    const publish = editor.querySelector(".sx-ticket-publish-v97");
    if (publish) publish.classList.toggle("active", step === 4);
  }

  function wizard(){
    const editor = document.querySelector(".sx-ticket-editor");
    if (!editor || editor.dataset.v97Ready === "1") return;
    editor.dataset.v97Ready = "1";
    const body = editor.querySelector(".sx-editor-body");
    if (!body) return;
    const nav = document.createElement("div");
    nav.className = "sx-ticket-wizard-v97";
    nav.innerHTML = [1,2,3,4].map((n,i) => `<button type="button" data-step="${n}">${n}. ${["Général","Équipe","Panel","Publication"][i]}</button>`).join("");
    body.before(nav);
    const publish = document.createElement("div");
    publish.className = "sx-ticket-publish-v97";
    publish.innerHTML = '<b>Vérification finale</b>Contrôlez le nom, les rôles et les boutons, puis cliquez sur <strong>Enregistrer</strong>. Si ce panel est déjà publié, SentriX met à jour son message Discord. Les réglages avancés restent disponibles sans encombrer le parcours principal.';
    body.appendChild(publish);
    nav.querySelectorAll("button").forEach(button => button.addEventListener("click", () => { step = Number(button.dataset.step); applyStep(editor); }));
    applyStep(editor);
  }

  function sync(){
    document.body.classList.toggle("sx-ticket-v97", active());
    if (!active()) return;
    advancedSettings();
    guide();
    wizard();
  }
  new MutationObserver(sync).observe(document.documentElement, {subtree:true, childList:true});
  document.addEventListener("click", () => setTimeout(sync, 0), true);
  setInterval(sync, 900);
  sync();
})();
</script>
'''


def install_dashboard(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-ticket-simple-v97-js"' in html:
        return True
    payload = DASHBOARD_CSS + "\n" + DASHBOARD_JS
    dashboard.INDEX_HTML = html.replace("</body>", payload + "\n</body>", 1) if "</body>" in html else html + payload
    logger.info("V97 dashboard Tickets simplifié installé.")
    return 'id="sentrix-ticket-simple-v97-js"' in dashboard.INDEX_HTML


def install(dashboard=None) -> None:
    install_slash()
    if dashboard is not None:
        install_dashboard(dashboard)


__all__ = ["install", "install_slash", "install_dashboard", "_build_signature", "_needs_text_fallback"]
