"""24/11/2026 : candidature staff supprimée, petites fautes sanctionnées, logs abîmés.

1. « Que ferais-tu si un ami à toi enfreint une règle ? » était supprimé avec
   un avertissement : « ami » figure dans le dataset multilingue.
2. Majuscules et émojis : suppression sans aucune sanction.
3. Logs : une ligne vide devenait « > » affiché tel quel ; un long message
   était coupé au milieu d'une phrase.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import automod  # noqa: E402
from utils import automod_incident_card as carte  # noqa: E402
from utils import moderation_dataset as md  # noqa: E402
from utils import wide_logs  # noqa: E402

CANDIDATURE = (
    "11. Que ferais-tu si un ami à toi enfreint une règle ? Ça va pas changer "
    "je prendrai une sanction comme tout le monde et voilà"
)


def test_une_candidature_qui_parle_d_un_ami_n_est_pas_une_insulte():
    d = md.MultilingualModerationDataset()
    assert d.match(CANDIDATURE) is None
    for phrase in ("mon ami est là", "c'est hard ce niveau", "el coche del amigo", "I got it"):
        assert d.match(phrase) is None, phrase
    # Une vraie insulte adressée reste détectée.
    assert d.match("t'es qu'un connard") is not None


def test_majuscules_et_emojis_sont_retires_sans_sanction():
    # Le comportement réel (aucune escalade, ni anti-spam, ni mute) est vérifié
    # sur le bot booté par tools/petites_fautes_e2e.py (test_product_e2e).
    assert {"anticaps", "antiemoji"} <= automod.FILTRES_SANS_SANCTION


def test_une_ligne_vide_ne_laisse_plus_de_chevron_seul():
    texte = "Pub payantes\n\nPing @rôle inconnu\n\n\n1 jour - 2€ ou 2 Garama"
    rendu = wide_logs._message_quote(texte)
    assert all(ligne.startswith("> ") for ligne in rendu.splitlines()), rendu
    assert ">\n" not in rendu + "\n"
    assert rendu.count("> ​") == 2  # les lignes vides consécutives n'en font qu'une


def test_un_long_message_est_coupe_a_la_fin_d_une_phrase():
    phrase = "Je reste calme et je prends des preuves. "
    texte = phrase * 60  # ~2 400 caractères
    coupe = wide_logs.couper_a_la_phrase(texte, 1500)
    assert len(coupe) <= 1502
    assert coupe.endswith("preuves. …") or coupe.endswith("preuves. …".strip())
    assert coupe[:-2].rstrip().endswith(".")
    # 26/11/2026 (« fait que ça affiche tout ») : jusqu'à 3000 caractères le
    # message s'affiche EN ENTIER, réparti en champs de moins de 1024 ; au-delà
    # (message Nitro), l'aperçu coupé à la phrase + fichier joint demeure.
    champs, fichier = carte.champs(
        filter_name="antiinsult", reason="x", guild_id=1, channel_id=2, message_id=3,
        created_at=0, contenu=texte, deleted=1, deleted_ok=True, action=None, duree_s=None,
        infractions=0, spam_stage=0, memoire="", ref="SX-1",
    )
    morceaux = [v for k, v in champs.items() if k.startswith("Contenu")]
    assert fichier is None and all(len(v) < 1024 for v in morceaux)
    assert "\n".join(morceaux).count("preuves.") == 60
    tres_long = phrase * 90  # ~3 700 caractères
    champs, fichier = carte.champs(
        filter_name="antiinsult", reason="x", guild_id=1, channel_id=2, message_id=3,
        created_at=0, contenu=tres_long, deleted=1, deleted_ok=True, action=None, duree_s=None,
        infractions=0, spam_stage=0, memoire="", ref="SX-1",
    )
    apercu = [v for k, v in champs.items() if k.startswith("Contenu")]
    assert "preuves. …" in "".join(apercu) and fichier is not None
    assert all(len(v) < 1024 for v in apercu)  # champs d'embed valides
