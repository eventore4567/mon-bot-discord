from pathlib import Path

RULES_FLOW = Path("utils/rules_flow.py").read_text(encoding="utf-8")
VERIFICATION = Path("cogs/verification.py").read_text(encoding="utf-8")
HONEYPOT = Path("cogs/honeypot_verification_v48.py").read_text(encoding="utf-8")
RULES_SETUP = Path("cogs/verify_setup_interactive_v78.py").read_text(encoding="utf-8")


def test_rules_flow_compiles_and_versions_acceptance():
    compile(RULES_FLOW, "utils/rules_flow.py", "exec")
    assert "CREATE TABLE IF NOT EXISTS rules_acceptances" in RULES_FLOW
    assert "current_rules_version" in RULES_FLOW
    assert "sha256" in RULES_FLOW
    assert "accept_current_rules" in RULES_FLOW
    assert "has_accepted_current_rules" in RULES_FLOW


def test_rules_button_chains_into_reinforced_verification():
    assert "accept_current_rules" in VERIFICATION
    assert 'self.bot.get_cog("HoneypotVerification")' in VERIFICATION
    assert "HoneypotVerifyView" in VERIFICATION
    assert "Règlement accepté" in VERIFICATION


def test_reinforced_verification_requires_current_rules_version_twice():
    # Check before starting and again immediately before the final role grant.
    assert HONEYPOT.count("has_accepted_current_rules") >= 2
    assert "Le règlement a changé" in HONEYPOT
    assert "Lisez et acceptez d'abord le règlement" in HONEYPOT


def test_reinforced_verification_reuses_setup_verified_role():
    """Le rôle final vient de +setup, et de nulle part ailleurs.

    Ce test exigeait que le module RÉÉCRIVE le rôle en base
    (`set_guild_config(..., "verify_role", verified.id)`) après l'avoir lu au
    même endroit — une écriture redondante, héritée de l'époque où SentriX
    créait un rôle « Vérifié » tout seul quand il n'en trouvait pas.

    La règle a changé, et dans le sens strict : le module ne crée plus aucun
    rôle. Il lit celui que l'administrateur a choisi, et REFUSE de continuer
    s'il n'y en a pas, plutôt que d'en inventer un. Un rôle créé
    automatiquement donne des accès que personne n'a décidés.

    C'est donc cette garantie-là qu'on vérifie, pas l'écriture disparue.
    """
    assert 'configured_role_id = guild_conf["verify_role"]' in HONEYPOT, (
        "le rôle final ne vient plus de la configuration de +setup"
    )
    assert "_find_or_create_role(guild, \"Vérifié\")" not in HONEYPOT, (
        "SentriX recrée un rôle Vérifié au lieu d'utiliser celui de +setup"
    )
    assert "SentriX ne crée plus automatiquement de rôle Vérifié." in HONEYPOT, (
        "le refus explicite a disparu : sans rôle configuré, que se passe-t-il ?"
    )


def test_rules_channel_stays_visible_to_unverified_members():
    assert "le règlement doit rester lisible avant la vérification" in HONEYPOT
    assert "règlement lisible avant vérification" in RULES_SETUP
    assert "ancien salon de règlement masqué avant vérification" in RULES_SETUP


def test_rules_setup_is_explicitly_separate_from_reinforced_verification():
    assert "Ce système gère le **règlement** séparément de la vérification renforcée." in RULES_SETUP
    assert "Toute modification future invalidera automatiquement les anciennes acceptations." in RULES_SETUP
    assert "open_setup_interaction" in RULES_SETUP
