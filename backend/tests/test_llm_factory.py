"""LLM 工厂的 Mock/真实配置选择测试。"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings
from app.services.llm_service import (
    LLMServiceError,
    MockLLMService,
    OpenAICompatibleLLMService,
    create_llm_service,
)


FAKE_KEY = "fake-deepseek-key"


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "development",
        "llm_provider": None,
        "llm_mock_enabled": True,
        "llm_api_key": None,
        "llm_base_url": "https://api.deepseek.com",
        "llm_model": "deepseek-flash",
        "llm_timeout_seconds": 7.0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_development_defaults_to_mock() -> None:
    service = create_llm_service(_settings())

    assert isinstance(service, MockLLMService)


def test_explicit_mock_is_selected_in_development() -> None:
    service = create_llm_service(
        _settings(
            llm_mock_enabled=True,
            llm_provider="deepseek",
            llm_api_key=FAKE_KEY,
        )
    )

    assert isinstance(service, MockLLMService)


def test_production_rejects_mock() -> None:
    with pytest.raises(LLMServiceError) as exc_info:
        create_llm_service(_settings(environment="production"))

    assert exc_info.value.code == "llm_not_configured"
    assert exc_info.value.status_code == 503
    assert "production" in str(exc_info.value)


def test_complete_real_configuration_creates_openai_compatible_service() -> None:
    service = create_llm_service(
        _settings(
            llm_mock_enabled=False,
            llm_provider="deepseek",
            llm_api_key=FAKE_KEY,
        )
    )

    assert isinstance(service, OpenAICompatibleLLMService)


def test_incomplete_real_configuration_does_not_fallback_to_mock() -> None:
    with pytest.raises(LLMServiceError) as exc_info:
        create_llm_service(
            _settings(
                llm_mock_enabled=False,
                llm_provider="deepseek",
                llm_api_key=None,
            )
        )

    assert exc_info.value.code == "llm_not_configured"
    assert exc_info.value.status_code == 503
    assert "LLM_API_KEY" in str(exc_info.value)
    assert FAKE_KEY not in str(exc_info.value)


def test_unsupported_provider_is_rejected_without_secret_leak() -> None:
    with pytest.raises(LLMServiceError) as exc_info:
        create_llm_service(
            _settings(
                llm_mock_enabled=False,
                llm_provider="unsupported",
                llm_api_key=FAKE_KEY,
            )
        )

    assert exc_info.value.code == "llm_not_configured"
    assert FAKE_KEY not in str(exc_info.value)
