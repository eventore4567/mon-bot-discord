"""Anti-spam SentriX : pas de sanctions sur des réponses courtes normales."""
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils.security_duplicate_window import DuplicateMessageWindow


def test_three_short_replies_are_not_duplicate_spam():
    tracker = DuplicateMessageWindow(window_seconds=12, threshold=3)
    for word in ("mdr", "oui", "lol", "ok", "+1", "merci"):
        for index in range(4):
            assert not tracker.add(1, 10, word, now=float(index))
    # Le compteur de débit principal prend toujours en charge un flood réel.


def test_meaningful_identical_messages_still_trigger():
    tracker = DuplicateMessageWindow(window_seconds=12, threshold=3)
    phrase = "Rejoignez mon serveur maintenant"
    assert not tracker.add(1, 10, phrase, now=0)
    assert not tracker.add(1, 10, phrase, now=1)
    assert tracker.add(1, 10, phrase, now=2)


def test_different_messages_with_identical_long_prefix_are_distinct():
    tracker = DuplicateMessageWindow(window_seconds=12, threshold=3)
    prefix = "a" * 320
    assert not tracker.add(1, 10, prefix + " une première fin", now=0)
    assert not tracker.add(1, 10, prefix + " une autre fin", now=1)
    assert not tracker.add(1, 10, prefix + " une troisième fin", now=2)


def test_normalization_and_expiry_are_kept():
    tracker = DuplicateMessageWindow(window_seconds=12, threshold=3)
    assert not tracker.add(1, 10, "BONJOUR tout le monde", now=0)
    assert not tracker.add(1, 10, "bonjour   TOUT le monde", now=1)
    assert not tracker.add(1, 10, "bonjour tout le monde", now=20)
    assert not tracker.add(1, 10, "bonjour tout le monde", now=21)
    assert tracker.add(1, 10, "bonjour tout le monde", now=22)


def test_members_and_guilds_are_isolated():
    tracker = DuplicateMessageWindow(window_seconds=12, threshold=3)
    msg = "Promotion répétée dans les salons"
    assert not tracker.add(1, 10, msg, now=1)
    assert not tracker.add(1, 11, msg, now=2)
    assert not tracker.add(2, 10, msg, now=3)
    assert not tracker.add(1, 10, msg, now=4)
    assert tracker.add(1, 10, msg, now=5)
