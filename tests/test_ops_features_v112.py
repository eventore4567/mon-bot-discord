import pytest

from sentrix_ops_features_v112 import should_downgrade_dataset_match


def test_precise_phrase_and_group_matches_are_never_downgraded():
    assert should_downgrade_dataset_match("exemple insultant", "phrase") is False
    assert should_downgrade_dataset_match("exemple insultant", "groupe_de_mots") is False
    assert should_downgrade_dataset_match("exemple insultant", "mot_ou_phrase_sans_espace") is False


def test_isolated_term_in_clear_explanatory_context_is_downgraded():
    assert should_downgrade_dataset_match("ça veut dire quoi le mot exemple", "mot") is True
    assert should_downgrade_dataset_match("définition du mot exemple", "mot") is True


def test_short_direct_message_is_not_downgraded():
    assert should_downgrade_dataset_match("insulte", "mot") is False
    assert should_downgrade_dataset_match("tu es insulte", "mot") is False


def test_code_or_quote_context_needs_enough_context():
    assert should_downgrade_dataset_match("`mot` signifie quelque chose", "mot") is True
    assert should_downgrade_dataset_match("`mot`", "mot") is False
