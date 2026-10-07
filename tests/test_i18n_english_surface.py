from pathlib import Path

import discord
import pytest

from cogs import language_runtime


POLICY_SOURCE = Path("cogs/final_interaction_policy.py").read_text(encoding="utf-8")
LANG_SOURCE = Path("cogs/language_runtime.py").read_text(encoding="utf-8")


def test_language_runtime_and_final_policy_compile():
    compile(LANG_SOURCE, "cogs/language_runtime.py", "exec")
    compile(POLICY_SOURCE, "cogs/final_interaction_policy.py", "exec")


def test_english_surface_translates_core_sentrix_ui():
    text = (
        "Règlement · Vérification renforcée · Sécurité · Invitations · "
        "Activer / réparer · Commande introuvable."
    )
    translated = language_runtime.english_ui_text(text, setup=True)
    assert "Rules" in translated
    assert "Reinforced verification" in translated
    assert "Security" in translated
    assert "Invites" in translated
    assert "Enable / repair" in translated
    assert "Unknown command" in translated


def test_english_surface_preserves_code_urls_and_mentions():
    raw = "Règlement : \x60Règlement\x60 <#123456789012345678> https://example.com/Règlement Sécurité"
    translated = language_runtime.english_ui_text(raw, setup=True)
    assert translated.startswith("Rules")
    assert "\x60Règlement\x60" in translated
    assert "<#123456789012345678>" in translated
    assert "https://example.com/Règlement" in translated
    assert translated.endswith("Security")


def test_embed_translation_preserves_free_form_body():
    embed = discord.Embed(
        title="Vérification renforcée",
        description="Règlement raconté librement par un utilisateur.",
    )
    embed.add_field(name="Raison", value="Règlement et Sécurité sont mes mots.", inline=False)
    language_runtime.translate_embed_in_place(embed, setup=False, preserve_body=True)
    assert embed.title == "Reinforced verification"
    assert embed.description == "Règlement raconté librement par un utilisateur."
    assert embed.fields[0].value == "Règlement et Sécurité sont mes mots."


@pytest.mark.asyncio
async def test_component_translation_changes_buttons_and_select_options():
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Activer / réparer"))
    select = discord.ui.Select(
        placeholder="Choisir un module à configurer",
        options=[discord.SelectOption(label="Sécurité", value="security")],
    )
    view.add_item(select)
    language_runtime.translate_view_in_place(view, setup=True)
    assert view.children[0].label == "Enable / repair"
    assert view.children[1].placeholder == "Choose a module to configure"
    assert view.children[1].options[0].label == "Security"


def test_final_transport_localizes_every_major_discord_surface():
    assert "async def _localize_outgoing" in POLICY_SOURCE
    for marker in (
        "async def context_send",
        "async def messageable_send",
        "async def message_edit",
        "async def response_send",
        "async def response_edit",
        "async def edit_original",
        "async def webhook_send",
    ):
        start = POLICY_SOURCE.index(marker)
        chunk = POLICY_SOURCE[start:start + 1800]
        assert "_localize_outgoing(" in chunk, marker


def test_language_confirmation_now_promises_broad_interface_coverage():
    assert "commands, panels, errors, setup, verification, security" in LANG_SOURCE

def test_english_surface_never_mangles_the_server_name():
    """La traduction est une substitution de SOUS-CHAÎNES : SETUP_EN_REPLACEMENTS
    contient ("Serveur", "Server"), appliqué par ``str.replace`` sur tout le
    fragment. Un serveur nommé « Serveur de Jayden » devenait donc « Server de
    Jayden » — on abîmait la donnée de l'utilisateur, pas l'étiquette.

    Mesuré en production le 07/10/2026 sur ``+setup``, qui affiche le nom du
    serveur en gras. ``_UI_PROTECTED_RE`` protégeait le code, les URL et les
    mentions, mais rien n'empêchait d'écrire dans un nom interpolé.
    """
    for nom in ("Serveur de Jayden", "Mon Serveur", "Serveur"):
        texte = f"# Configuration de SentriX\n**{nom}** en attente"
        assert nom in language_runtime.english_ui_text(texte, setup=True, protect=(nom,)), nom
        # Sans protection, le défaut existe toujours : c'est bien le paramètre
        # qui protège, pas un hasard de formulation.
        assert nom not in language_runtime.english_ui_text(texte, setup=True)


def test_protecting_a_name_does_not_block_real_label_translation():
    """Protéger le nom du serveur ne doit pas geler toute la traduction."""
    rendu = language_runtime.english_ui_text(
        "Modifications en attente", setup=True, protect=("Mon Serveur",)
    )
    assert "Unsaved changes" in rendu

def test_view_translation_also_protects_the_server_name():
    """SentriX rend presque tout en Components V2, donc le texte d'un panneau
    passe par translate_view_in_place et non par l'embed. La protection doit
    valoir sur ce chemin aussi : c'est lui qui abîmait « Serveur test » dans
    +setup, et le transport n'avait pas le dernier mot — setup_experience_v74
    retraduit sa propre vue après chaque clic.
    """
    import discord

    vue = discord.ui.View()
    vue.add_item(discord.ui.Button(label="Serveur de Jayden"))
    vue.add_item(discord.ui.Button(label="Modifications en attente"))
    language_runtime.translate_view_in_place(vue, setup=True, protect=("Serveur de Jayden",))
    etiquettes = [item.label for item in vue.children]
    assert "Serveur de Jayden" in etiquettes, etiquettes
    assert "Unsaved changes" in etiquettes, etiquettes


def test_exact_translation_never_overrides_protection():
    """La couche exacte court-circuitait le garde : un serveur nommé exactement
    « Serveur », ou un membre surnommé « Membre », était renommé."""
    for nom in ("Serveur", "Membre", "Rôle"):
        assert language_runtime.english_ui_text(nom, setup=True, protect=(nom,)) == nom
        # Non protégée, la même étiquette doit bien se traduire.
        assert language_runtime.english_ui_text(nom, setup=True) != nom

def test_substitution_respecte_les_frontieres_de_mot():
    """Un `str.replace` nu mordait à l'intérieur des mots. Les pluriels doivent
    donc être déclarés explicitement — sans ("Serveurs", "Servers"),
    « **Serveurs** · 1 » restait français."""
    rendu = language_runtime.english_ui_text("**Serveurs** · 1")
    assert "**Servers** · 1" in rendu, rendu
    # Et un mot plus long n'est pas amputé par une entrée plus courte.
    assert language_runtime._remplacer_mot("Membres couverts", "Membre", "Member") == "Membres couverts"


def test_aucune_entree_ne_traverse_un_nom_protege():
    """Les noms protégés COUPENT le fragment : une entrée de dictionnaire qui
    les enjambe ne peut jamais matcher. « Arrivée de SentriX » arrivait au
    traducteur comme « **Arrivée de » et ressortait « Joined de SentriX ».
    On traduit la partie qui précède le nom, et l'ordre des mots tient."""
    rendu = language_runtime.english_ui_text(
        "**Arrivée de SentriX** · test", protect=("SentriX",)
    )
    assert "Arrival of SentriX" in rendu, rendu
    assert " de SentriX" not in rendu, rendu


def test_la_barre_de_progression_de_niveau_nest_pas_un_tuple():
    """``utils.stats_service.progress_bar`` rend un TUPLE (barre, pourcentage).
    cogs/levels.py l'affectait entier puis l'interpolait, ce qui affichait
    ``('▱▱▱...', 0)`` — le repr Python brut — dans +niveau, vu par tous les
    membres. Lu sur l'AST : l'appel doit être dépaqueté."""
    import ast
    from pathlib import Path

    arbre = ast.parse(Path("cogs/levels.py").read_text(encoding="utf-8"))
    trouves = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Assign):
            continue
        valeur = noeud.value
        if not isinstance(valeur, ast.Call):
            continue
        if not ast.unparse(valeur.func).endswith("progress_bar"):
            continue
        trouves.append(noeud)
        cible = noeud.targets[0]
        assert isinstance(cible, ast.Tuple), (
            "progress_bar rend un tuple : l'affecter à un nom unique affiche son "
            f"repr brut. Trouvé : {ast.unparse(noeud)[:80]}"
        )
    assert trouves, "aucun appel à progress_bar trouvé dans cogs/levels.py"

#: Mots de liaison français. Traduits ISOLÉMENT, ils mordent au milieu des phrases
#: et produisent du franglais. Mesuré : ("encore", "still") transformait « Cette
#: récompense n'est pas encore disponible » en « n'est pas still disponible ».
MOTS_OUTILS = frozenset({
    "le", "la", "les", "un", "une", "des", "du", "de", "et", "ou", "où", "à", "au",
    "aux", "dans", "pour", "par", "sur", "avec", "sans", "sous", "ce", "cet", "cette",
    "ces", "son", "sa", "ses", "leur", "leurs", "est", "sont", "pas", "ne", "en",
    "y", "il", "elle", "ils", "elles", "vous", "nous", "je", "tu", "on", "que",
    "qui", "quoi", "dont", "encore", "déjà", "toujours", "jamais", "très", "plus",
    "moins", "aussi", "alors", "donc", "mais", "car", "si", "comme", "tout", "tous",
})


def test_aucun_mot_outil_nest_traduit_isolement():
    """Un mot de liaison ne porte pas de sens à lui seul : le traduire hors
    contexte produit une phrase moitié française moitié anglaise. Les phrases
    qui en contiennent doivent être déclarées en ENTIER.
    """
    fautifs = [
        (source, cible)
        for source, cible in list(language_runtime.SURFACE_EN_REPLACEMENTS)
        + list(language_runtime.SETUP_EN_REPLACEMENTS)
        if source.strip().casefold() in MOTS_OUTILS
    ]
    assert fautifs == [], (
        "ces entrées traduisent un mot de liaison isolé, ce qui produit du "
        f"franglais au milieu des phrases : {fautifs}"
    )


def test_une_phrase_avec_un_mot_outil_est_traduite_en_entier():
    """Le cas exact qui a été mesuré sur +daily."""
    rendu = language_runtime.english_ui_text(
        "Cette récompense n'est pas encore disponible."
    )
    assert rendu == "This reward is not available yet.", rendu
    assert "still" not in rendu, rendu

def test_aucune_entree_ne_produit_un_melange():
    """Une traduction doit laisser la phrase ENTIÈREMENT anglaise, ou intacte —
    jamais à moitié.

    C'est la garde qui aurait attrapé mes deux erreurs toute seule :
    ("encore", "still") rendait « Cette récompense n'est pas still disponible »,
    et ("Aucune", "None") + ("configurée", "configured") rendaient « None clé
    OpenAI n'est configured sur ce bot ». Les deux fois, le mot existait aussi
    DANS des phrases, pas seulement comme étiquette.

    Le corpus est figé depuis un balayage réel du bot booté
    (``tools/i18n_coverage_sweep.py``), donc il décrit ce que les membres voient
    vraiment, et non des exemples inventés.
    """
    import json
    import re
    from pathlib import Path

    corpus = json.loads(
        Path("tests/fixtures/phrases_francaises_rendues.json").read_text(encoding="utf-8")
    )
    assert len(corpus) > 200, f"corpus trop maigre : {len(corpus)}"
    accent = re.compile(r"[àâäéèêëîïôöùûüç]")

    # Les mêmes littéraux que le transport protège en production : nom du serveur,
    # du bot, de l'auteur. Sans eux le test accuserait la traduction d'abîmer
    # « Serveur test », ce qui n'arrive justement pas en vrai.
    protection = ("Serveur test", "SentriX", "admin")

    melanges = []
    for phrase in corpus:
        rendu = language_runtime.english_ui_text(
            phrase, setup=True, protect=protection
        ) or phrase
        if rendu != phrase and accent.search(rendu):
            melanges.append((phrase[:60], rendu[:60]))

    assert melanges == [], (
        "ces phrases ressortent moitié françaises moitié anglaises ; la ou les "
        "entrées responsables traduisent un mot qui apparaît DANS une phrase, "
        f"pas seulement comme étiquette :\n" + "\n".join(
            f"  {avant!r}\n    -> {apres!r}" for avant, apres in melanges[:8]
        )
    )
