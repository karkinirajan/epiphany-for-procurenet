# Work done: epiphany-for-procurenet

Branch: `chore/modernize` (local, not pushed). Date: 2026-11-01.

## What was there
Nine tracked files: **four near-identical scripts** of 963, 986, 1,162 and 1,262 lines (successive iterations from 11 to 16 August 2023: `original_script.py` → `mycode.py` → `wc_script.py` → `wc_script-5-fixedDB.py`), a `requirements.txt` of 25 pins, a README that tells you to run a `main.py` that does not exist, `.vscode/settings.json`, `.gitignore` and `LICENSE`. No tests. The newest script (`wc_script-5-fixedDB.py`) is the live one and is what this branch ports; the other three are earlier versions of it.

## Credentials in the code and in the git history (the most important part of this report)
All four scripts had live-looking credentials **hard-coded in the source**: an OpenAI API key, a WooCommerce REST consumer key and secret for the store, and the PostgreSQL user, password and host. (Counts only; nothing was printed or tested.)
- In history: **2 distinct OpenAI-key-shaped values, 2 distinct WooCommerce key/secret values (`ck_` / `cs_`), and 6 database-password lines, across 5 of the 14 commits**, in 8 file paths (`main.py`, `config.py`, `ePiphany/…` and the four scripts). The store's address and the database host are in the same lines.
- In the working tree now: none. Every setting comes from the environment (`.env.example` has demo values).
- **Rotate:** the OpenAI key; the WooCommerce REST API key pair (it has read/write access to a client's live catalog); the PostgreSQL password, and check which networks can reach that database.
- Removing them from history means rewriting it and force-pushing, which is a push you must do yourself.

## Bugs and risks found in the live script, and what was done
| Problem | Fix |
|---|---|
| Every request had `ssl=False`: TLS verification off while the store's keys travel in Basic auth | Verification on; `WOOCOMMERCE_VERIFY_SSL=false` is an explicit choice that `epiphany check` warns about |
| One request put the consumer key and secret in the query string | Basic-auth header only |
| When the model returned no categories, `categories: []` was sent, which **removes every category** of the product | Empty categories, tags and Yoast fields are not sent at all |
| The model's category IDs were sent as they came | Only categories that exist in the store, no duplicates, at most three |
| The product name was set to the SEO title even when that was empty | Not sent when empty; `RENAME_TO_SEO_TITLE=false` keeps names |
| Only the first page of categories was fetched (WooCommerce returns 10 by default), so the model was offered, and the code accepted, only 10 | All pages; fetched once per run (it was fetched twice per product) |
| The category loop ran until it had `count` products and never ended if `count` was too high | Pages until an empty page |
| Failures were saved with the literal text `"product_name"` and `"product_url"`; and the INSERT used columns (`short_description`, `description`) that the table was never created with, so failures were silently **not recorded**; `retry` selected the same missing columns | `failed_products` gets `error` and `failed_at`; the real name, URL and error are stored; retry re-fetches the product from the store |
| `generated_responses` was written to but never created | Created (its definition is inferred from the INSERT) |
| "Resume previous update" re-fetched the products already updated and skipped every one of them (it did nothing) | Resume runs the catalog again, skipping what is done |
| `update_product_on_woocommerce` returned `(None, None)` on failure and the caller then called `.get()` on it; the `except` in `handle_update` used variables that might not exist yet | One outcome object per product; a failure never stops the run |
| Each prompt was JSON-wrapped and then every backslash was deleted, so each paragraph break reached the model as the letters `nn` | The prompts are word for word as before, sent as plain text |
| The model's answer was cut at its *last* `{` and had every backslash and newline deleted, which broke any answer with an escaped quote in its HTML | The first valid JSON object is decoded properly (code fences and prose around it are fine); an unusable answer is asked for again (`GENERATION_ATTEMPTS`) |
| The generated HTML was published without any clean-up (it comes from a model that was given supplier-written text) | An allow-list (nh3): scripts, iframes, forms, event handlers and `javascript:` links are removed |
| Up to 25 products at once, a 2 s sleep per update, a thread pool created per call, `time.sleep` in threads, and a token-count heuristic for rate limits | `CONCURRENCY` (default 5), the SDK's own retries for rate limits |
| `openai.ChatCompletion` with `gpt-4` hard-coded | The current SDK; `OPENAI_MODEL` (no default) |
| Importing the file connected to PostgreSQL, played a 3-second spinner demo and built the store client | Nothing happens at import; clients are built when a command needs them |
| A single shared database connection, rolled back by hand after errors | One autocommit connection used one statement at a time |
| `last_update` was set only on first insert, so "recent updates" was not ordered by recency | Refreshed on every update |
| Dead code: `request_with_retry`, `update_yoast_meta`, `get_seconds_elapsed`, `update_seconds_elapsed`, `remove_control_characters`, a commented-out `delete_tables()` | Not carried over |

## Added (not in the old script)
- `--dry-run`: generates and saves the text in `generated_responses`, changes nothing in the store.
- `original_content` + `epiphany restore ID`: each product's listing before its first rewrite is saved (first time only), so a rewrite can be undone. **Products rewritten by earlier runs have no saved original.**
- `epiphany check`: shows what is missing and whether the store and database answer.
- Scriptable commands and exit codes next to the old menu (which keeps its numbers).
- Retries with back-off on timeouts, 429 (honouring `Retry-After`) and 5xx for every store call.

## Changes by file
| Path | Before | Change |
|---|---|---|
| `wc_script-5-fixedDB.py` | 1,162 lines, the live script | split into `src/epiphany/` (`cli`, `pipeline`, `ai`, `content`, `prompts`, `sanitize`, `woo`, `db`, `config`) |
| `original_script.py`, `mycode.py`, `wc_script.py` | earlier iterations | removed from the tree (nothing imports them; they stay in history). See below. |
| `requirements.txt` | 25 pins | `pyproject.toml` + `uv.lock` (35 packages), `.python-version` |
| `README.md` | features list, `python main.py` | rewritten to match the code |
| `.env.example` | absent | all 15 settings with demo values (a test keeps it in sync) |
| `.gitignore` | Python template | adds `.env.*` (not the example) and `.vscode/` |
| `.vscode/settings.json` | tracked | untracked (pylint/black editor settings) |
| `tests/` | absent | 154 tests |
| `.github/workflows/ci.yml` | absent | lint, format check, tests with a PostgreSQL service |
| `VERSIONS.md`, `work-done.md` | absent | written |

**About the three removed scripts.** The oldest one (`original_script.py`) used `asyncpg`, `bs4` and a different flow: generate, store, then *sanitise and verify* (`sanitize_and_verify_responses`, `view_responses_to_update`, `update_verified_responses_on_woocommerce`), then push. The newest script dropped that review step and pushed straight away. This port follows the newest; `--dry-run` plus `generated_responses` give back a way to look before pushing.

## Verification (actual runs)
- `uv run pytest -q`: **154 passed**, 100% line coverage of `src/epiphany`; `ruff check` and `ruff format --check` clean. The 11 store tests run on a real PostgreSQL 17.11 (each test in its own schema, dropped afterwards, none left) and skip without `TEST_DATABASE_URL`.
- Mutation checks (the defect put back, the suite must fail): 23, all caught (and the quieted-logger names, by a test that makes a real call): unknown or duplicate categories kept, an empty category list sent, an empty SEO title blanking the name, a dry run that still updates, the original not saved, HTML not cleaned, categories fetched per product, failures stored with the literal names, TLS verification off by default, no retry on 429/5xx, keys in the query string, the *last* JSON object winning, no bound on concurrency, restore leaving the product marked updated, the update time not refreshed, the first original overwritten, the dry-run flag lost before the command, resume forcing a re-run, retry not forcing, only the first page of categories, an unusable answer not asked again, an empty description accepted, the prompt JSON-wrapped. (An earlier version of my driver mislabelled every mutant "survived" because it matched the word `failed` in lower case against pytest's `FAILED`; the exit code is what it trusts now.)
- **Two real bugs found by the new tests in my own code and fixed:** `epiphany --dry-run product 1` lost the flag (argparse let the sub-command's default overwrite it) and would have run for real on the live store; and the OpenAI SDK's HTTP client logs under `httpx2`, so quieting `httpx` left one log line per API call.
- The real `epiphany` command end to end against a local fake WooCommerce server, a local fake OpenAI server (the real SDK pointed at it) and the real PostgreSQL: `check`; `--dry-run` (0 updated, 1 generated, store untouched); a real update (descriptions cleaned, invalid category `999` and the duplicate dropped, string `"10"` accepted); a catalog run with one product that the model fails on (exit 1, recorded with its error); `retry` (cleared); `resume` (4 skipped, 2 updated); `restore` (original back); a missing product (exit 1). Every store request was authenticated, none had a key in its query string, no payload had an empty category list or a `<script>`, `<iframe>` or `onclick`.
- A count-only secret scan of the working tree (nothing) and of the whole history (see the first section).
- **Not verified:** a real OpenAI answer; a real WooCommerce store or Yoast (the fake speaks the endpoints the old script used); that `gpt-4` is still available; a GitHub Actions run.

## Needs your attention
- **Rotate** the credentials listed in the first section.
- **Set `OPENAI_MODEL`.** The old script always used `gpt-4`. The prompts also say "data up to September 2021"; I left their text alone.
- **Run `--dry-run` on a few products and read the output before a catalog run.** The prompts now reach the model without the `nn` glitch and answers are parsed differently, so results can differ from earlier runs.
- Concurrency defaults to 5 (the old code allowed 25 at once). Raise `CONCURRENCY` if the store and your OpenAI limits allow it.
- A product now fails as a whole if either answer is unusable (the old code sometimes updated with half of the text). Failed products are listed with their error, and `retry` processes them again.
- If the store uses a self-signed certificate, set `WOOCOMMERCE_VERIFY_SSL=false` knowingly.
- The product name is still set to the generated SEO title, as before. Set `RENAME_TO_SEO_TITLE=false` if that is not wanted.
- Nothing pushed. To publish: `git push -u origin chore/modernize`
