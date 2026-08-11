"""Durcissement XSS de l'interface Community Growth sans changer son API."""
from __future__ import annotations


def install(module) -> None:
    if getattr(module, "_sentrix_community_security", False):
        return
    html = module.COMMUNITY_HTML
    anchor = 'const $=id=>document.getElementById(id);let csrf="",guildId="",options={};'
    escaped = anchor + '\nconst esc=s=>String(s??"").replace(/[&<>"\\\']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\\"":"&quot;","\\\'":"&#39;"}[c]));'
    if anchor in html and "const esc=" not in html:
        html = html.replace(anchor, escaped, 1)

    replacements = {
        '${placeholder}</option>`+items.map(x=>`<option value="${x.id}">${x.name}</option>': '${esc(placeholder)}</option>`+items.map(x=>`<option value="${x.id}">${esc(x.name)}</option>',
        'installed.map(g=>`<option value="${g.id}">${g.name}</option>`)': 'installed.map(g=>`<option value="${g.id}">${esc(g.name)}</option>`)',
        '<strong>${f.title}</strong>': '<strong>${esc(f.title)}</strong>',
        '<strong>#${a.id} · ${a.form_title}</strong>': '<strong>#${a.id} · ${esc(a.form_title)}</strong>',
        '<b>${x.question}</b><br>${x.answer||\'<span class=meta>Sans réponse</span>\'}': '<b>${esc(x.question)}</b><br>${x.answer?esc(x.answer):\'<span class=meta>Sans réponse</span>\'}',
        'setNotice(`Centre communautaire prêt pour ${options.brand}.`)': 'setNotice(`Centre communautaire prêt pour ${esc(options.brand)}.`)',
    }
    for old, new in replacements.items():
        html = html.replace(old, new)

    module.COMMUNITY_HTML = html
    module._sentrix_community_security = True
