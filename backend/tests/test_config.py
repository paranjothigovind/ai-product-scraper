import pytest

from scraper.core.config import ConfigError, Settings, load_settings

VALID = {
    "ANTHROPIC_API_KEY": "sk-test-secret",
    "MODEL_EXTRACT": "a",
    "MODEL_JUDGE": "b",
    "MODEL_ESCALATE": "c",
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
    "REDIS_URL": "redis://localhost:6379",
    "S3_ENDPOINT": "http://localhost:9000",
    "S3_BUCKET": "bkt",
    "S3_ACCESS_KEY_ID": "k",
    "S3_SECRET_ACCESS_KEY": "s",
}


def load(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    for key, value in {**VALID, **overrides}.items():
        monkeypatch.setenv(key, value)
    return load_settings(_env_file=None)


def test_spec_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    s = load(monkeypatch)
    assert (s.max_pages_total, s.max_retries, s.min_quality, s.plan_cap_products) == (
        50,
        2,
        0.75,
        500,
    )


def test_coerces_numeric_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    assert load(monkeypatch, MAX_PAGES_TOTAL="10").max_pages_total == 10


def test_invalid_env_names_the_field_but_never_echoes_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in VALID:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", "not-a-url-hunter2")
    with pytest.raises(ConfigError) as exc:
        load_settings(_env_file=None)
    text = str(exc.value)
    assert "anthropic_api_key" in text
    assert "database_url" in text
    assert "hunter2" not in text


def test_secrets_are_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    s = load(monkeypatch)
    assert "sk-test-secret" not in repr(s)
    assert s.anthropic_api_key.get_secret_value() == "sk-test-secret"
