import pytest

from epiphany.config import ConfigError, Settings

ALL = (
    "WOOCOMMERCE_URL", "WOOCOMMERCE_CONSUMER_KEY", "WOOCOMMERCE_CONSUMER_SECRET", "WOOCOMMERCE_VERIFY_SSL",
    "DATABASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL", "CONCURRENCY", "RENAME_TO_SEO_TITLE",
)  # fmt: skip


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ALL:
        monkeypatch.delenv(name, raising=False)


def test_nothing_is_configured_by_default_and_the_safe_choices_are_the_defaults():
    s = Settings()
    assert s.woocommerce_url == s.woocommerce_consumer_key == s.woocommerce_consumer_secret == ""
    assert s.database_url == s.openai_api_key == ""
    assert s.openai_model == ""  # no model is assumed (the old code hard-coded gpt-4)
    assert s.woocommerce_verify_ssl is True  # the old code switched verification off everywhere
    assert s.concurrency == 5 and s.rename_to_seo_title is True
    assert (s.request_attempts, s.generation_attempts) == (5, 2)


def test_settings_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("WOOCOMMERCE_URL", "https://shop.example")
    monkeypatch.setenv("WOOCOMMERCE_VERIFY_SSL", "false")
    monkeypatch.setenv("CONCURRENCY", "9")
    monkeypatch.setenv("RENAME_TO_SEO_TITLE", "no")
    s = Settings()
    assert (s.woocommerce_url, s.woocommerce_verify_ssl, s.concurrency, s.rename_to_seo_title) == (
        "https://shop.example", False, 9, False,
    )  # fmt: skip


def test_require_names_every_missing_setting_in_upper_case():
    with pytest.raises(ConfigError) as caught:
        Settings(openai_api_key="k").require("openai_api_key", "openai_model", "database_url")
    assert caught.value.names == ["OPENAI_MODEL", "DATABASE_URL"]
    assert str(caught.value) == "Missing configuration: OPENAI_MODEL, DATABASE_URL"
    Settings(openai_api_key="k").require("openai_api_key")  # present: no error
