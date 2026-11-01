from pathlib import Path

from epiphany.config import Settings

EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def names_in_example():
    names = set()
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            names.add(line.split("=", 1)[0].strip())
    return names


def test_every_setting_is_documented_in_the_example_file():
    missing = {name.upper() for name in Settings.model_fields} - names_in_example()
    assert missing == set(), f"add these to .env.example: {sorted(missing)}"


def test_the_example_file_names_no_unknown_setting():
    unknown = names_in_example() - {name.upper() for name in Settings.model_fields}
    assert unknown == set(), f"not settings (typo or removed?): {sorted(unknown)}"


def test_the_example_file_loads_as_valid_settings():
    """Inline comments and empty values must parse, so `cp .env.example .env` works as is."""
    s = Settings(_env_file=str(EXAMPLE))
    assert s.woocommerce_url == "https://shop.example.com"
    assert s.woocommerce_verify_ssl is True and s.concurrency == 5 and s.rename_to_seo_title is True
    assert s.log_file == "" and s.openai_model == "demo-model-name"
