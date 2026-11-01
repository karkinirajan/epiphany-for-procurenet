import logging

import pytest

from epiphany import cli
from epiphany.config import ConfigError, Settings
from epiphany.woo import WooError

from .conftest import FakeGenerator, FakeStore, FakeWoo, product


@pytest.fixture
def env(woo, generator, store):
    """A Runtime over the fakes, and a helper that runs a command line and returns (code, output)."""
    settings = Settings(rename_to_seo_title=True)
    runtime = cli.Runtime(settings, woo=woo, store=store, generator=generator)
    lines = []

    async def invoke(*argv):
        lines.clear()
        code = await cli.run(list(argv), settings, runtime, out=lines.append)
        return code, "\n".join(lines)

    return invoke, woo, generator, store, lines


# ------------------------------------------------------------------------------------ product
async def test_product_updates_one_product(env):
    invoke, woo, _, store, _ = env
    code, out = await invoke("product", "3")
    assert code == 0 and "Done: 1 updated" in out
    assert [pid for pid, _ in woo.updates] == [3] and 3 in store.updated


async def test_product_not_found(env):
    invoke, woo, *_ = env
    code, out = await invoke("product", "999")
    assert code == 1 and out == "Product not found." and woo.updates == []


async def test_a_failure_gives_exit_code_1_and_names_the_product_and_error(env):
    invoke, woo, *_ = env
    woo.fail_update.add(2)
    code, out = await invoke("product", "2")
    assert (
        code == 1 and "failed: 2 Product 2" in out and "WooError" in out and "Done: 1 failed" in out
    )


async def test_dry_run_changes_nothing(env):
    invoke, woo, _, store, _ = env
    code, out = await invoke("product", "1", "--dry-run")
    assert code == 0 and "1 dry-run" in out
    assert woo.updates == [] and store.updated == {} and 1 in store.generated


@pytest.mark.parametrize(
    "argv",
    [
        ["--dry-run", "product", "1"],
        ["product", "1", "--dry-run"],
        ["--dry-run", "catalog", "--ids", "odd"],
        ["--dry-run", "category", "10"],
        ["--dry-run", "retry"],
    ],
)
async def test_a_dry_run_flag_is_never_lost_whichever_side_of_the_command_it_is_on(env, argv):
    """Regression: a flag before the command used to be overwritten by the command's own default,
    so this ran for real on the live store."""
    invoke, woo, _, store, _ = env
    woo.products_by_id[1]["category_ids"] = [10]
    store.failed_rows[1] = ("Product 1", "u", "boom")
    await invoke(*argv)
    assert woo.updates == [] and store.updated == {}


def test_every_flag_survives_in_both_positions():
    parser = cli.build_parser()
    before = parser.parse_args(["--dry-run", "--force", "--concurrency", "3", "product", "1"])
    after = parser.parse_args(["product", "1", "--dry-run", "--force", "--concurrency", "3"])
    for args in (before, after):
        assert (args.dry_run, args.force, args.concurrency) == (True, True, 3)
    none = parser.parse_args(["product", "1"])
    assert (none.dry_run, none.force, none.concurrency) == (False, False, None)


async def test_the_flags_work_before_or_after_the_command(env):
    invoke, woo, *_ = env
    assert (await invoke("--dry-run", "product", "1"))[1].endswith("1 dry-run")
    assert (await invoke("product", "1", "--dry-run"))[1].endswith("1 dry-run")


async def test_force_reprocesses_an_updated_product(env):
    invoke, woo, _, store, _ = env
    store.updated[1] = ("n", "u")
    assert (await invoke("product", "1"))[1].endswith("1 skipped")
    assert (await invoke("product", "1", "--force"))[1].endswith("1 updated")


async def test_concurrency_is_taken_from_the_flag(env):
    invoke, _, generator, *_ = env
    await invoke("catalog", "--concurrency", "1")
    assert generator.max_in_flight == 1


# ---------------------------------------------------------------------------------- category
async def test_category_updates_its_products(env):
    invoke, woo, *_ = env
    woo.products_by_id[1]["category_ids"] = [10]
    woo.products_by_id[2]["category_ids"] = [10]
    code, out = await invoke("category", "10")
    assert (
        code == 0
        and "category 'Solvents'" in out
        and sorted(pid for pid, _ in woo.updates) == [1, 2]
    )


async def test_unknown_category(env):
    invoke, woo, *_ = env
    assert await invoke("category", "999") == (1, "Category not found.")
    assert woo.updates == []


# ------------------------------------------------------------------------- catalog and resume
async def test_catalog_updates_everything_by_default(env):
    invoke, woo, *_ = env
    code, out = await invoke("catalog")
    assert code == 0 and "6 updated" in out and len(woo.updates) == 6


@pytest.mark.parametrize(("ids", "expected"), [("odd", [1, 3, 5]), ("even", [2, 4, 6])])
async def test_catalog_can_be_split_by_odd_or_even_id(env, ids, expected):
    invoke, woo, *_ = env
    await invoke("catalog", "--ids", ids)
    assert sorted(pid for pid, _ in woo.updates) == expected


async def test_resume_skips_what_is_done_and_processes_the_rest(env):
    """The old "resume" re-fetched the products that were already done and skipped each one."""
    invoke, woo, _, store, _ = env
    for pid in (1, 2, 3):
        store.updated[pid] = ("n", "u")
    code, out = await invoke("resume")
    assert code == 0 and "already updated are skipped" in out and "3 updated, 3 skipped" in out
    assert sorted(pid for pid, _ in woo.updates) == [4, 5, 6]


# ------------------------------------------------------------------------ failed, retry, recent
async def test_failed_lists_products_with_their_error(env):
    invoke, _, _, store, _ = env
    assert await invoke("failed") == (0, "No failed products.")
    store.failed_rows[7] = ("Acetone", "https://s/7", "WooError: 400")
    code, out = await invoke("failed")
    assert (
        code == 0
        and "Product ID: 7, Name: Acetone, URL: https://s/7" in out
        and "    WooError: 400" in out
    )


async def test_retry_refetches_the_product_forces_it_and_clears_the_failure(env):
    invoke, woo, _, store, _ = env
    store.updated[2] = ("n", "u")  # even an "updated" product is retried: it failed afterwards
    store.failed_rows[2] = ("Product 2", "u", "boom")
    code, out = await invoke("retry")
    assert code == 0 and "Retrying 1 failed" in out and "1 updated" in out
    assert [pid for pid, _ in woo.updates] == [2] and store.failed_rows == {}


async def test_retry_drops_products_that_no_longer_exist(env):
    invoke, woo, _, store, _ = env
    store.failed_rows[999] = ("Gone", "u", "boom")
    code, out = await invoke("retry")
    assert "product 999 (Gone) no longer exists" in out and store.failed_rows == {}
    assert woo.updates == []


async def test_retry_with_nothing_failed(env):
    invoke, *_ = env
    assert await invoke("retry") == (0, "No failed products.")


async def test_recent_lists_and_limits(env):
    invoke, _, _, store, _ = env
    assert await invoke("recent") == (0, "Nothing has been updated yet.")
    for pid in (1, 2, 3):
        store.updated[pid] = (f"P{pid}", f"u{pid}")
    code, out = await invoke("recent", "--limit", "2")
    assert out.count("Product ID:") == 2


# -------------------------------------------------------------------------------------- restore
async def test_restore_puts_the_original_back(env):
    invoke, woo, _, store, _ = env
    await invoke("product", "1")
    code, out = await invoke("restore", "1")
    assert code == 0 and "Restored product 1 to its original listing ('Product 1')" in out
    assert woo.products_by_id[1]["name"] == "Product 1" and 1 not in store.updated


async def test_restore_without_a_saved_original(env):
    invoke, *_ = env
    assert await invoke("restore", "4") == (1, "no saved original for product 4")


# ---------------------------------------------------------------------------------------- check
def settings_with(**kw):
    base = dict(
        woocommerce_url="https://shop.example",
        woocommerce_consumer_key="ck_demo",
        woocommerce_consumer_secret="cs_demo",
        database_url="postgresql://demo",
        openai_api_key="sk-demo",
        openai_model="demo-model",
    )
    return Settings(**{**base, **kw})


async def run_check(settings, woo=None, store=None):
    lines = []
    runtime = cli.Runtime(settings, woo=woo or FakeWoo(), store=store or FakeStore())
    code = await cli.run(["check"], settings, runtime, out=lines.append)
    return code, "\n".join(lines)


async def test_check_lists_every_missing_setting():
    code, out = await run_check(Settings())
    assert code == 1
    assert (
        "WooCommerce: MISSING WOOCOMMERCE_URL, WOOCOMMERCE_CONSUMER_KEY, WOOCOMMERCE_CONSUMER_SECRET"
        in out
    )
    assert (
        "PostgreSQL: MISSING DATABASE_URL" in out
        and "OpenAI: MISSING OPENAI_API_KEY, OPENAI_MODEL" in out
    )
    assert "reachable" not in out and "connected" not in out


async def test_check_with_everything_configured_and_reachable():
    code, out = await run_check(settings_with())
    assert (
        code == 0
        and "WooCommerce: reachable, keys accepted" in out
        and "PostgreSQL: connected" in out
    )
    assert "WARNING" not in out


async def test_check_warns_when_tls_verification_is_off():
    code, out = await run_check(settings_with(woocommerce_verify_ssl=False))
    assert "WARNING: TLS verification for the store is switched off" in out


async def test_check_reports_a_store_that_rejects_the_keys():
    class Rejecting(FakeWoo):
        async def get_category(self, category_id):
            raise WooError("WooCommerce answered 401: Sorry, you cannot list resources.", 401)

    code, out = await run_check(settings_with(), woo=Rejecting())
    assert code == 1 and "WooCommerce: WooCommerce answered 401" in out


async def test_check_reports_an_unreachable_database_without_printing_its_url():
    settings = settings_with(database_url="postgresql://user:pw-demo@127.0.0.1:1/db")
    lines = []
    runtime = cli.Runtime(settings, woo=FakeWoo())
    code = await cli.run(["check"], settings, runtime, out=lines.append)
    out = "\n".join(lines)
    assert code == 1 and "PostgreSQL: OperationalError" in out and "pw-demo" not in out


# ------------------------------------------------------------------------------------- the menu
async def test_the_menu_dispatches_every_option_with_the_old_numbers(env):
    invoke, woo, _, store, _ = env
    answers = iter(["1", "3", "2", "x", "5", "6", "odd", "7", "4", "0"])
    outputs = []
    settings = Settings()
    runtime = cli.Runtime(settings, woo=woo, store=store, generator=FakeGenerator())
    args = cli.build_parser().parse_args([])

    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        # option 1 asks for a product id, option 2 for a category id
        if prompt.startswith("Enter the ID of the product"):
            return "1"
        if prompt.startswith("Enter the ID of the category"):
            return "999"
        return next(answers)

    code = await cli.cmd_menu(runtime, args, outputs.append, ask)
    text = "\n".join(outputs)
    assert code == 0
    assert "Select an option:" in text and "7. Resume previous update" in text
    assert "Done: 1 updated" in text  # option 1
    assert "No failed products." in text  # option 3 (and 4)
    assert "Category not found." in text  # option 2
    assert "Invalid option. Please try again." in text  # "x"
    assert "Recently updated products:" in text  # option 5
    assert "Updating the catalog (ids: odd)" in text  # option 6
    assert "Resuming: products that are already updated are skipped." in text  # option 7
    assert sorted({pid for pid, _ in woo.updates}) == [1, 3, 5, 2, 4, 6] or len(woo.updates) == 6


async def test_the_menu_treats_an_unknown_parity_as_all(env):
    _, woo, _, store, _ = env
    answers = iter(["6", "banana", "0"])
    out = []
    runtime = cli.Runtime(Settings(), woo=woo, store=store, generator=FakeGenerator())
    await cli.cmd_menu(
        runtime, cli.build_parser().parse_args([]), out.append, lambda p: next(answers)
    )
    assert any("ids: all" in line for line in out) and len(woo.updates) == 6


# --------------------------------------------------------------------------------------- parser
def test_the_parser_rejects_bad_input():
    parser = cli.build_parser()
    for argv in (["product"], ["product", "abc"], ["catalog", "--ids", "banana"], ["nonsense"]):
        with pytest.raises(SystemExit) as caught:
            parser.parse_args(argv)
        assert caught.value.code == 2


def test_no_command_means_the_menu():
    assert cli.build_parser().parse_args([]).command is None


# ------------------------------------------------------------------------ runtime and main()
def test_the_runtime_builds_the_clients_from_the_settings(monkeypatch):
    seen = {}

    class RecordingWoo:
        def __init__(self, url, key, secret, **kw):
            seen.update(url=url, key=key, secret=secret, **kw)

    monkeypatch.setattr(cli, "WooClient", RecordingWoo)
    runtime = cli.Runtime(
        settings_with(woocommerce_verify_ssl=False, request_timeout=12, request_attempts=7)
    )
    runtime.woo()
    assert seen == {
        "url": "https://shop.example", "key": "ck_demo", "secret": "cs_demo",
        "verify": False, "timeout": 12, "attempts": 7,
    }  # fmt: skip
    generator = cli.Runtime(settings_with(generation_attempts=4)).generator()
    assert generator.model == "demo-model" and generator.attempts == 4


@pytest.mark.parametrize(
    ("build", "missing"),
    [
        (
            lambda r: r.woo(),
            "WOOCOMMERCE_URL, WOOCOMMERCE_CONSUMER_KEY, WOOCOMMERCE_CONSUMER_SECRET",
        ),
        (lambda r: r.generator(), "OPENAI_API_KEY, OPENAI_MODEL"),
    ],
)
def test_building_a_client_without_its_settings_names_what_is_missing(build, missing):
    with pytest.raises(ConfigError, match=missing):
        build(cli.Runtime(Settings()))


async def test_the_store_needs_a_database_url():
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        await cli.Runtime(Settings()).store()


async def test_the_updater_takes_the_rename_setting(woo, generator, store):
    runtime = cli.Runtime(
        Settings(rename_to_seo_title=False), woo=woo, store=store, generator=generator
    )
    await (await runtime.updater()).process(product(1))
    assert "name" not in woo.updates[0][1]


async def test_close_closes_what_was_opened(woo, store):
    runtime = cli.Runtime(Settings(), woo=woo, store=store)
    await runtime.close()
    assert woo.closed and store.closed
    await cli.Runtime(Settings()).close()  # nothing opened: nothing to close


def test_main_reports_missing_configuration_and_returns_2(monkeypatch, capsys):
    for name in ("DATABASE_URL", "WOOCOMMERCE_URL", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert cli.main(["failed"]) == 2
    err = capsys.readouterr().err
    assert "Missing configuration: DATABASE_URL" in err and "See .env.example" in err


def test_main_returns_130_on_ctrl_c(monkeypatch):
    def interrupted(coroutine, *args, **kwargs):
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.asyncio, "run", interrupted)
    assert cli.main(["failed"]) == 130


def test_logging_goes_to_stderr_and_optionally_a_file(tmp_path):
    log = tmp_path / "run.log"
    cli.setup_logging(Settings(log_file=str(log), log_level="warning"))
    logging.getLogger("epiphany").warning("something happened")
    logging.getLogger("epiphany").info("not shown at WARNING")
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = log.read_text()
    assert "something happened" in text and "not shown" not in text


def test_the_http_clients_per_request_lines_are_not_logged_at_info(tmp_path):
    """A real call through the OpenAI client: its HTTP layer logs 'HTTP Request: ...' at INFO under
    the name httpx2 (not httpx), which put one line per call into the log."""
    import asyncio
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from openai import AsyncOpenAI

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps(
                {"id": "c", "object": "chat.completion", "created": 1, "model": "m",
                 "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}]}
            ).encode()  # fmt: skip
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log = tmp_path / "run.log"
    cli.setup_logging(Settings(log_file=str(log), log_level="INFO"))

    async def call():
        client = AsyncOpenAI(api_key="demo", base_url=f"http://127.0.0.1:{server.server_port}/v1")
        await client.chat.completions.create(
            model="m", messages=[{"role": "user", "content": "hi"}]
        )

    asyncio.run(call())
    server.shutdown()
    logging.getLogger("epiphany").info("our own line")
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = log.read_text()
    assert "our own line" in text and "HTTP Request" not in text
