"""« @SentriX + » change le préfixe (administrateurs seulement)."""
from types import SimpleNamespace

from utils import mention_prefix as mp

BOT = SimpleNamespace(user=SimpleNamespace(id=42))


def _msg(content):
    return SimpleNamespace(content=content)


def test_symbole_court_apres_la_mention():
    for texte, attendu in (("<@42> +", "+"), ("<@!42> !", "!"), ("<@42>   s!", "s!"), ("<@42> ?", "?")):
        assert mp.prefixe_demande(BOT, _msg(texte)) == attendu, texte


def test_une_phrase_ou_une_autre_mention_reste_pour_l_ia():
    for texte in ("<@42> salut", "<@42> ok", "<@42> mute @x 10m", "<@7> +", "salut <@42> +",
                  "<@42> <@7>", "<@42> :smile:", "<@42> /help", "<@42> 123456", "<@42>"):
        assert mp.prefixe_demande(BOT, _msg(texte)) is None, texte


def test_reserve_aux_administrateurs():
    guild = SimpleNamespace(owner_id=1)
    admin = SimpleNamespace(id=2, guild_permissions=SimpleNamespace(administrator=True, manage_guild=False))
    gestion = SimpleNamespace(id=3, guild_permissions=SimpleNamespace(administrator=False, manage_guild=True))
    membre = SimpleNamespace(id=4, guild_permissions=SimpleNamespace(administrator=False, manage_guild=False))
    assert mp._peut_changer(SimpleNamespace(id=1), guild)
    assert mp._peut_changer(admin, guild) and mp._peut_changer(gestion, guild)
    assert not mp._peut_changer(membre, guild)
