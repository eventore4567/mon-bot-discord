"""Le corps narratif des journaux doit dire CE QUI a changé.

Deux bugs constatés en production :

- « Rôle modifié » ne montrait jamais le changement (nom, couleur,
  permissions) : narrative_body() avait bien une branche role_update, mais
  elle ne lisait que embed.description (toujours vide pour cet événement) et
  compact_fields() filtre les valeurs courtes comme « `ancien` → `nouveau` » ;
- role_add / role_remove n'avaient AUCUNE branche narrative : le corps
  restait entièrement vide, y compris le membre concerné.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = pathlib.Path(__file__).resolve().parent.parent

from utils import embeds  # noqa: E402
from utils.wide_logs import NO_PINGS, narrative_body  # noqa: E402


def test_role_modifie_montre_le_nom_avant_apres():
    e = embeds.canonical_log_embed(
        "Rôle modifié",
        fields=[
            ("Rôle", "<@&999888777666555444>", True),
            ("Nom", "`ancien` → `nouveau`", False),
        ],
    )
    corps = narrative_body(e, log_type="role_update")
    assert "ancien" in corps and "nouveau" in corps


def test_role_modifie_montre_la_couleur():
    e = embeds.canonical_log_embed(
        "Rôle modifié",
        fields=[
            ("Rôle", "<@&999888777666555444>", True),
            ("Couleur", "`#5865F2` → `#ED4245`", False),
        ],
    )
    corps = narrative_body(e, log_type="role_update")
    assert "#5865F2" in corps and "#ED4245" in corps


def test_role_modifie_montre_les_permissions():
    e = embeds.canonical_log_embed(
        "Rôle modifié",
        fields=[
            ("Rôle", "<@&999888777666555444>", True),
            ("Permissions ajoutées", "Gérer les rôles", False),
            ("Permissions supprimées", "Bannir des membres", False),
        ],
    )
    corps = narrative_body(e, log_type="role_update")
    assert "Gérer les rôles" in corps
    assert "Bannir des membres" in corps


def test_role_modifie_mentionne_le_role_pas_son_nom_brut():
    """Une mention de rôle reste toujours lisible, même si le nom réel du
    rôle contient des astérisques ou d'autres caractères qui casseraient un
    nom mis en gras par interpolation de chaîne."""
    e = embeds.canonical_log_embed(
        "Rôle modifié",
        fields=[("Rôle", "<@&999888777666555444>", True)],
    )
    corps = narrative_body(e, log_type="role_update", identity_name="*")
    assert "<@&999888777666555444>" in corps


def test_role_ajoute_mentionne_le_membre_et_le_role():
    e = embeds.canonical_log_embed(
        "Rôle ajouté",
        fields=[
            ("Membre", "<@153201041595183925>", True),
            ("Rôle", "<@&999888777666555444>", True),
        ],
    )
    corps = narrative_body(e, log_type="role_add", identity_id=153201041595183925)
    assert "<@153201041595183925>" in corps
    assert "<@&999888777666555444>" in corps
    assert "reçu" in corps


def test_role_retire_dit_perdu_pas_recu():
    e = embeds.canonical_log_embed(
        "Rôle retiré",
        fields=[
            ("Membre", "<@153201041595183925>", True),
            ("Rôle", "<@&999888777666555444>", True),
        ],
    )
    corps = narrative_body(e, log_type="role_remove", identity_id=153201041595183925)
    assert "perdu" in corps
    assert "reçu" not in corps


def test_le_salon_de_logs_bloque_toujours_la_notification():
    """La mention identifie le membre SANS le notifier : NO_PINGS est
    appliqué à l'envoi, indépendamment du texte que porte le panneau."""
    assert NO_PINGS.users is False
    assert NO_PINGS.roles is False
    assert NO_PINGS.everyone is False


def test_les_journaux_resistent_a_l_installation_reelle_du_bot():
    """sentrix_runtime.install() réassigne ENTIÈREMENT embeds.log_embed au
    démarrage réel — pas seulement ce qu'il appelle en interne. Protéger
    _base/add_fields ne suffit pas : canonical_log_embed/canonical_normalize_log
    doivent rester intacts même APRÈS une vraie installation.

    L'installation est globale et irréversible pour le process : ce test
    tourne dans un sous-processus dédié pour ne pas polluer la suite.
    """
    resultat = subprocess.run(
        [sys.executable, str(RACINE / "tools" / "verif_logs_apres_install.py")],
        capture_output=True,
        text=True,
        cwd=str(RACINE),
        env={**os.environ, "DISCORD_TOKEN": "x"},
        timeout=120,
    )
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
    assert "les journaux resistent a l'installation reelle" in resultat.stdout


def test_surnom_modifie_montre_avant_apres():
    e = embeds.canonical_log_embed(
        "Surnom modifié",
        fields=[
            ("Membre", "<@153201041595183925>", True),
            ("Avant", "Jayden", True),
            ("Après", "Jay", True),
        ],
    )
    corps = narrative_body(e, log_type="member_update")
    assert "Jayden" in corps and "Jay" in corps
    assert "changé de surnom" in corps


def test_invitation_creee_montre_le_lien_et_le_salon():
    e = embeds.canonical_log_embed(
        "Invitation créée",
        fields=[
            ("Créateur", "<@111222333444555666>", True),
            ("Salon", "<#222333444555666777>", True),
            ("Lien", "https://discord.gg/abc", False),
            ("Expire", "Jamais", True),
        ],
    )
    corps = narrative_body(e, log_type="invite_create")
    assert "https://discord.gg/abc" in corps
    assert "<#222333444555666777>" in corps
    assert "<@111222333444555666>" in corps


def test_invitation_supprimee_montre_le_code():
    e = embeds.canonical_log_embed(
        "Invitation supprimée",
        fields=[
            ("Responsable", "<@111222333444555666>", True),
            ("Code", "abc123", True),
        ],
    )
    corps = narrative_body(e, log_type="invite_delete")
    assert "abc123" in corps


def test_serveur_modifie_montre_ce_qui_a_change():
    e = embeds.canonical_log_embed(
        "Serveur modifié",
        fields=[("Nom", "`Ancien` → `Nouveau`", False)],
    )
    corps = narrative_body(e, log_type="guild_update")
    assert "Ancien" in corps and "Nouveau" in corps


def test_voice_logs_v2_transmet_l_event_type_precis():
    """voice_logs_v2.py calculait le bon event_type localement (pour la clé de
    dédup) mais passait « log_voice » — un alias de CATÉGORIE — à _send().
    canonical_event_type() s'arrête dès qu'il reconnaît une catégorie et ne
    tente alors JAMAIS le rattachement par titre : voice_join/voice_leave
    tombaient dans le fallback générique et perdaient jusqu'à la mention du
    membre, la seule information qui comptait."""
    import ast

    chemin = RACINE / "cogs" / "voice_logs_v2.py"
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    appels = [
        n for n in ast.walk(arbre)
        if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("_send")
    ]
    assert appels, "aucun appel _send trouvé"
    for appel in appels:
        args = [ast.unparse(a) for a in appel.args]
        assert "'log_voice'" not in args, args
        assert "event_type" in args, args


def test_deplacement_vocal_mentionne_le_membre():
    e = embeds.canonical_log_embed(
        "Activité vocale — Connexion",
        fields=[
            ("Membre", "<@153201041595183925>", False),
            ("Salon", "<#222333444555666777>", False),
        ],
    )
    corps = narrative_body(e, log_type="voice_join")
    assert "<@153201041595183925>" in corps
    assert "<#222333444555666777>" in corps
