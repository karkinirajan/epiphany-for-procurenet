# Versions

Read from `uv.lock` and the installed packages on 2026-11-01.

| Component | Version | Was | Where it is set |
|---|---|---|---|
| Python | 3.13 (3.13.18 here) | "3.8 or above" in the README | `.python-version`, `pyproject.toml` |
| httpx | 0.28.1 | aiohttp 3.8.5 | `pyproject.toml` |
| openai | 3.42.0 (`AsyncOpenAI`) | 0.27.8 (`openai.ChatCompletion`, removed from the SDK) | |
| psycopg | 3.3.6 (async) | psycopg2-binary 2.9.7 | |
| pydantic / pydantic-settings | 2.14.2 / 2.16.2 | absent | |
| nh3 | 0.3.7 | absent | HTML clean-up |
| pytest / pytest-asyncio / pytest-cov (dev) | 9.2.0 / 1.4.1 / 7.1.0 | absent | |
| ruff (dev) | 0.17.3 | absent (the old editor settings pointed at pylint and black) | |
| PostgreSQL | 17 (tested on 17.11) | not stated | CI service container |

35 packages are locked. The old `requirements.txt` pinned 25, among them `asyncio==3.4.3` (an obsolete PyPI package of the same name as the standard library module, which it can shadow), `halo`, `spinners`, `log-symbols`, `colorama`, `termcolor`, `tqdm`, `phpserialize`, `simplejson`, `requests` and the `WooCommerce` client library (the old code only used it to hold the URL and keys). The oldest script also imported `bs4` and `asyncpg`, which were not listed.

No model name is pinned: the old code hard-coded `gpt-4`; `OPENAI_MODEL` is a setting because which models an account can use could not be verified here.

## Verified here

- 154 tests pass, 100% line coverage of `src/epiphany`; `ruff check` and `ruff format --check` are clean.
- The store tests ran on a real PostgreSQL 17.11, including an upgrade from the old script's two tables.
- The real `epiphany` command, end to end, against a local fake WooCommerce server, a local fake OpenAI server (the real SDK pointed at it with `OPENAI_BASE_URL`) and the real PostgreSQL: `check`, `--dry-run`, a real update, a catalog run with one failing product, `failed`, `retry`, `resume`, `recent`, `restore`.

## Not verified here

- A real OpenAI answer, and a real WooCommerce store (the fake speaks the endpoints the old script used: products, categories, `PUT /products/{id}`). Whether Yoast accepts its `_yoast_wpseo_*` fields through the product `meta_data` was not changed from the old script and not checked.
- That the models the old script used (`gpt-4`) are still available to the account.
- A GitHub Actions run.
