"""Settings from environment variables (or a local ``.env``). Nothing is read at import time: the
old script opened a PostgreSQL connection, started a spinner demo and built a WooCommerce client
while being imported, with every key hard-coded in the file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    def __init__(self, names):
        self.names = [name.upper() for name in names]
        super().__init__("Missing configuration: " + ", ".join(self.names))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The WooCommerce store (REST API keys with read/write permission)
    woocommerce_url: str = ""
    woocommerce_consumer_key: str = ""
    woocommerce_consumer_secret: str = ""
    woocommerce_verify_ssl: bool = True  # the old code turned verification off on every request
    request_timeout: float = 60.0
    request_attempts: int = 5

    # PostgreSQL: which products were updated or failed, what was generated, the originals
    database_url: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = ""  # no default: set a chat model your account can use
    openai_timeout: float = 120.0
    generation_attempts: int = 2  # asks again when the answer is not the JSON that was requested

    # Behaviour
    concurrency: int = 5  # products processed at once (the old code allowed 25)
    rename_to_seo_title: bool = True  # the old code always set the product name to the SEO title
    log_level: str = "INFO"
    log_file: str = ""

    def require(self, *names):
        missing = [name for name in names if not getattr(self, name)]
        if missing:
            raise ConfigError(missing)
