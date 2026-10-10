import os
from unittest.mock import Mock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import ai_service


def test_text_client_uses_optional_compatible_base_url():
    client = Mock()
    ai_service._TEXT_CLIENT = None

    with (
        patch.object(ai_service.config, "OPENAI_API_KEY", "local-test-key"),
        patch.object(
            ai_service.config,
            "OPENAI_TEXT_BASE_URL",
            "http://127.0.0.1:1234/v1",
            create=True,
        ),
        patch("openai.AsyncOpenAI", return_value=client) as constructor,
    ):
        assert ai_service.get_client() is client

    constructor.assert_called_once_with(
        api_key="local-test-key",
        timeout=ai_service.REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
        base_url="http://127.0.0.1:1234/v1",
    )
    ai_service._TEXT_CLIENT = None


def test_text_client_keeps_openai_default_when_base_url_is_empty():
    client = Mock()
    ai_service._TEXT_CLIENT = None

    with (
        patch.object(ai_service.config, "OPENAI_API_KEY", "production-test-key"),
        patch.object(ai_service.config, "OPENAI_TEXT_BASE_URL", "", create=True),
        patch("openai.AsyncOpenAI", return_value=client) as constructor,
    ):
        assert ai_service.get_client() is client

    constructor.assert_called_once_with(
        api_key="production-test-key",
        timeout=ai_service.REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
    ai_service._TEXT_CLIENT = None


def test_image_client_never_uses_text_base_url():
    client = Mock()
    ai_service._IMAGE_CLIENT = None

    with (
        patch.object(ai_service.config, "OPENAI_API_KEY", "image-test-key"),
        patch.object(
            ai_service.config,
            "OPENAI_TEXT_BASE_URL",
            "http://127.0.0.1:1234/v1",
            create=True,
        ),
        patch("openai.AsyncOpenAI", return_value=client) as constructor,
    ):
        assert ai_service.get_image_client() is client

    constructor.assert_called_once_with(
        api_key="image-test-key",
        timeout=ai_service.IMAGE_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
    ai_service._IMAGE_CLIENT = None
