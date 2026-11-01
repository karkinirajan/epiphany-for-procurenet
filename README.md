# ePiphany for Procurenet

A command-line tool that rewrites the product listings of a WooCommerce store with OpenAI: a new short description (with up to three categories), a new long description, an SEO title, a meta description, a focus keyword and tags. The results are written back through the WooCommerce REST API (Yoast fields included) and every product's outcome is recorded in PostgreSQL, so a long run can fail, be retried and be resumed.

> It edits a live store. Run it with `--dry-run` on a few products first, and read what it generated.

## What it does for each product

1. Skips the product if it is already recorded as updated (use `--force` to redo it).
2. Asks the model for the short description + categories and for the long description + SEO fields (two prompts, in parallel; an answer that is not the requested JSON is asked for again).
3. Cleans the HTML (only product-listing markup is kept: no scripts, iframes, forms or event handlers) and keeps only categories that exist in the store (at most three).
4. Saves the listing **as it was** (first time only), then updates the product, then records it as updated.
5. On any failure: records the product and the error, keeps the generated text, and carries on with the next product.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) (Python 3.13) and a PostgreSQL database.

```bash
uv sync
cp .env.example .env                 # fill in the store, database and OpenAI settings
docker run -d --name epiphany-db -e POSTGRES_PASSWORD=demo-password -p 5432:5432 postgres:17-alpine   # if you need a database
uv run epiphany check                # what is configured, does the store accept the keys, does the database answer
uv run epiphany --dry-run product 123   # generate for one product, change nothing in the store
uv run epiphany product 123          # the real thing
```

## Commands

| Command | What it does |
|---|---|
| `epiphany` / `epiphany menu` | The interactive menu of the old script (same numbers 1 to 7 and 0). |
| `epiphany product ID` | Update one product. |
| `epiphany category ID` | Update every product of a category. |
| `epiphany catalog [--ids all\|odd\|even]` | Update the whole catalog; `odd` / `even` split the work between two runs. |
| `epiphany resume` | Run the catalog again; products already updated are skipped. |
| `epiphany failed` / `epiphany retry` | List the failed products with their error / process them again. |
| `epiphany recent [--limit N]` | The latest updates. |
| `epiphany restore ID` | Put a product back to the listing saved before its first rewrite. |
| `epiphany check` | Check the configuration and the connections (no OpenAI call). |

Flags (before or after the command): `--dry-run` (generate and save the text, change nothing in the store), `--force` (also process products already updated), `--concurrency N`.
Exit codes: 0 done, 1 a product failed or was not found, 2 a setting is missing, 130 interrupted.

## Configuration

Environment variables or a local `.env`; [`.env.example`](./.env.example) lists them all with demo values.

| Variable | Default | Meaning |
|---|---|---|
| `WOOCOMMERCE_URL`, `WOOCOMMERCE_CONSUMER_KEY`, `WOOCOMMERCE_CONSUMER_SECRET` | none | The store and REST API keys with read/write permission. |
| `WOOCOMMERCE_VERIFY_SSL` | `true` | Set `false` only for a store with a self-signed certificate (`check` warns). |
| `REQUEST_TIMEOUT`, `REQUEST_ATTEMPTS` | 60, 5 | Per request; timeouts, 429 and 5xx are retried with a back-off. |
| `DATABASE_URL` | none | `postgresql://user:password@host:5432/db` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | none | The model has no default on purpose: use one your account can use. |
| `OPENAI_TIMEOUT`, `GENERATION_ATTEMPTS` | 120, 2 | |
| `CONCURRENCY` | 5 | Products processed at once. |
| `RENAME_TO_SEO_TITLE` | `true` | The product name is set to the generated SEO title (as before). `false` keeps the name; the Yoast title is still set. |
| `LOG_LEVEL`, `LOG_FILE` | `INFO`, empty | Progress lines go to stderr, and to the file if set. |

## The database

Created and upgraded automatically (`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`, so an existing database from the old script keeps its rows):

| Table | Holds |
|---|---|
| `updated_products` | id, name, URL, time of the last update |
| `failed_products` | id, name, URL, the error, when it failed |
| `generated_responses` | the generated text per product (dry runs, and updates that failed) |
| `original_content` | each product's name and descriptions before its first rewrite (used by `restore`) |

## Project structure

```
src/epiphany/
├── cli.py        commands, the menu, flags, logging
├── pipeline.py   one product's steps, the bounded run, payload building, restore
├── ai.py         the OpenAI calls (asks again on an unusable answer)
├── content.py    the expected answers and the tolerant JSON parsing
├── prompts.py    the two prompts
├── sanitize.py   HTML allow-list
├── woo.py        the WooCommerce REST client (retries, pagination)
├── db.py         PostgreSQL (schema, upserts)
└── config.py     settings
tests/            154 tests; the store tests run on a real PostgreSQL
```

## Testing

```bash
docker run -d --name epiphany-test-db -e POSTGRES_PASSWORD=demo-only -p 15433:5432 postgres:17-alpine
export TEST_DATABASE_URL=postgresql://postgres:demo-only@127.0.0.1:15433/postgres
uv run pytest -q          # 154 tests, 100% line coverage; the 11 database tests skip without TEST_DATABASE_URL
uv run ruff check . && uv run ruff format --check .
```

OpenAI and WooCommerce are faked at their boundaries (the store client is tested at the HTTP level with `httpx.MockTransport`); each test database gets its own schema, dropped afterwards.

## Versions

[VERSIONS.md](./VERSIONS.md). What changed and what needs your attention (**including credentials in the git history**): [work-done.md](./work-done.md).

## License

MIT, see [LICENSE](./LICENSE).
