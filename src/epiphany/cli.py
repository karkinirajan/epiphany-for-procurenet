import argparse
import asyncio
import logging
import sys

import httpx
from openai import AsyncOpenAI

from .ai import ContentGenerator
from .config import ConfigError, Settings
from .db import Store
from .pipeline import Updater, fetch_products, restore
from .woo import WooClient, WooError

logger = logging.getLogger("epiphany")


class Runtime:
    """Builds the WooCommerce client, the database and the generator when a command first needs
    them, so ``failed`` does not ask for an OpenAI key and ``check`` can say what is missing."""

    def __init__(self, settings, *, woo=None, store=None, generator=None):
        self.settings = settings
        self._woo, self._store, self._generator = woo, store, generator

    def woo(self):
        if self._woo is None:
            s = self.settings
            s.require("woocommerce_url", "woocommerce_consumer_key", "woocommerce_consumer_secret")
            self._woo = WooClient(
                s.woocommerce_url,
                s.woocommerce_consumer_key,
                s.woocommerce_consumer_secret,
                verify=s.woocommerce_verify_ssl,
                timeout=s.request_timeout,
                attempts=s.request_attempts,
            )
        return self._woo

    async def store(self):
        if self._store is None:
            self.settings.require("database_url")
            self._store = await Store.connect(self.settings.database_url)
        return self._store

    def generator(self):
        if self._generator is None:
            s = self.settings
            s.require("openai_api_key", "openai_model")
            client = AsyncOpenAI(api_key=s.openai_api_key, timeout=s.openai_timeout)
            self._generator = ContentGenerator(client, s.openai_model, s.generation_attempts)
        return self._generator

    async def updater(self, *, dry_run=False, force=False, concurrency=None):
        s = self.settings
        return Updater(
            self.woo(),
            self.generator(),
            await self.store(),
            dry_run=dry_run,
            force=force,
            rename=s.rename_to_seo_title,
            concurrency=concurrency or s.concurrency,
        )

    async def close(self):
        if self._woo is not None:
            await self._woo.close()
        if self._store is not None:
            await self._store.close()


# ------------------------------------------------------------------------------------ commands
async def _run_products(runtime, products, args, out, *, force=None):
    updater = await runtime.updater(
        dry_run=args.dry_run,
        force=args.force if force is None else force,
        concurrency=args.concurrency,
    )
    report = await updater.run(products)
    for outcome in report.failed:
        out(f"  failed: {outcome.product_id} {outcome.name}: {outcome.error}")
    out(f"Done: {report.summary()}")
    return 1 if report.failed else 0


async def cmd_product(runtime, args, out=print):
    product = await runtime.woo().get_product(args.id)
    if not product:
        out("Product not found.")
        return 1
    return await _run_products(runtime, [product], args, out)


async def cmd_category(runtime, args, out=print):
    category = await runtime.woo().get_category(args.id)
    if not category:
        out("Category not found.")
        return 1
    out(f"Updating products in category '{category.get('name')}'...")
    products = await fetch_products(runtime.woo(), category=args.id)
    return await _run_products(runtime, products, args, out)


async def cmd_catalog(runtime, args, out=print):
    out(f"Updating the catalog (ids: {args.ids})...")
    products = await fetch_products(runtime.woo(), parity=args.ids)
    return await _run_products(runtime, products, args, out)


async def cmd_resume(runtime, args, out=print):
    """The old "resume" fetched the products that were already updated and then skipped each of them
    (so it did nothing). Resuming means running the catalog again: finished products are skipped."""
    args.ids = "all"
    out("Resuming: products that are already updated are skipped.")
    return await cmd_catalog(runtime, args, out)


async def cmd_failed(runtime, args, out=print):
    rows = await (await runtime.store()).failed()
    out("Failed products:" if rows else "No failed products.")
    for product_id, name, url, error in rows:
        out(f"Product ID: {product_id}, Name: {name}, URL: {url}")
        if error:
            out(f"    {error}")
    return 0


async def cmd_retry(runtime, args, out=print):
    store = await runtime.store()
    rows = await store.failed()
    if not rows:
        out("No failed products.")
        return 0
    out(f"Retrying {len(rows)} failed products...")
    products = []
    for product_id, name, _url, _error in rows:
        product = await runtime.woo().get_product(product_id)
        if product is None:
            out(
                f"  product {product_id} ({name}) no longer exists in the store; dropped from the list."
            )
            await store.clear_failed(product_id)
            continue
        products.append(product)
    return await _run_products(runtime, products, args, out, force=True)


async def cmd_recent(runtime, args, out=print):
    rows = await (await runtime.store()).recent_updates(args.limit)
    out("Recently updated products:" if rows else "Nothing has been updated yet.")
    for product_id, name, url, when in rows:
        out(f"Product ID: {product_id}, Name: {name}, URL: {url}, Last update: {when}")
    return 0


async def cmd_restore(runtime, args, out=print):
    try:
        name = await restore(runtime.woo(), await runtime.store(), args.id)
    except LookupError as error:
        out(str(error))
        return 1
    out(f"Restored product {args.id} to its original listing ('{name}').")
    return 0


async def cmd_check(runtime, args, out=print):
    """Says what is configured and whether the store and the database answer. It makes no OpenAI call."""
    s, problems = runtime.settings, 0
    for label, names in {
        "WooCommerce": (
            "woocommerce_url",
            "woocommerce_consumer_key",
            "woocommerce_consumer_secret",
        ),
        "PostgreSQL": ("database_url",),
        "OpenAI": ("openai_api_key", "openai_model"),
    }.items():
        missing = [n.upper() for n in names if not getattr(s, n)]
        out(f"{label}: " + ("configured" if not missing else "MISSING " + ", ".join(missing)))
        problems += bool(missing)
    if not s.woocommerce_verify_ssl:
        out(
            "WARNING: TLS verification for the store is switched off (WOOCOMMERCE_VERIFY_SSL=false)."
        )
    if s.woocommerce_url and s.woocommerce_consumer_key and s.woocommerce_consumer_secret:
        try:
            await runtime.woo().get_category(0)  # any authenticated call; 404 is fine, 401 is not
            out("WooCommerce: reachable, keys accepted")
        except (WooError, httpx.HTTPError) as error:
            out(f"WooCommerce: {error}")
            problems += 1
    if s.database_url:
        try:
            await runtime.store()
            out("PostgreSQL: connected, tables ready")
        except Exception as error:  # noqa: BLE001
            out(f"PostgreSQL: {type(error).__name__}")
            problems += 1
    return 1 if problems else 0


# ------------------------------------------------------------------------------------- the menu
MENU = """
Select an option:
1. Update one product
2. Update a whole category of products
3. View failed products
4. Retry failed products
5. View recent updates
6. Update entire catalog
7. Resume previous update
0. Exit"""


async def cmd_menu(runtime, args, out=print, ask=input):
    """The interactive menu of the old script, with the same numbers."""
    while True:
        out(MENU)
        choice = ask("Enter an option (1/2/3/4/5/6/7/0): ").strip()
        if choice == "0":
            return 0
        if choice == "1":
            args.id = ask("Enter the ID of the product to update: ").strip()
            await cmd_product(runtime, args, out)
        elif choice == "2":
            args.id = ask("Enter the ID of the category to update: ").strip()
            await cmd_category(runtime, args, out)
        elif choice == "3":
            await cmd_failed(runtime, args, out)
        elif choice == "4":
            await cmd_retry(runtime, args, out)
        elif choice == "5":
            args.limit = None
            await cmd_recent(runtime, args, out)
        elif choice == "6":
            ids = ask("Which product IDs? (all/odd/even) [all]: ").strip().lower() or "all"
            args.ids = ids if ids in ("all", "odd", "even") else "all"
            await cmd_catalog(runtime, args, out)
        elif choice == "7":
            await cmd_resume(runtime, args, out)
        else:
            out("Invalid option. Please try again.")


COMMANDS = {
    "menu": cmd_menu,
    "product": cmd_product,
    "category": cmd_category,
    "catalog": cmd_catalog,
    "resume": cmd_resume,
    "failed": cmd_failed,
    "retry": cmd_retry,
    "recent": cmd_recent,
    "restore": cmd_restore,
    "check": cmd_check,
}


def common_flags(after_command):
    """``--dry-run``, ``--force`` and ``--concurrency``, accepted before or after the command.
    The copy on the sub-commands has no default of its own (``SUPPRESS``): with one, argparse lets
    the sub-command's default overwrite a flag given before it, so ``epiphany --dry-run product 1``
    would have run for real."""
    flags = argparse.ArgumentParser(add_help=False)
    unset = argparse.SUPPRESS
    flags.add_argument(
        "--dry-run",
        action="store_true",
        default=unset if after_command else False,
        help="generate and save the text, change nothing in the store",
    )
    flags.add_argument(
        "--force",
        action="store_true",
        default=unset if after_command else False,
        help="also process products that are already updated",
    )
    flags.add_argument(
        "--concurrency",
        type=int,
        default=unset if after_command else None,
        help="products processed at once",
    )
    return flags


def build_parser():
    common = common_flags(after_command=True)
    parser = argparse.ArgumentParser(
        prog="epiphany",
        description="Rewrite WooCommerce product listings with OpenAI.",
        parents=[common_flags(after_command=False)],
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("menu", parents=[common], help="the interactive menu (default)")
    p = sub.add_parser("product", parents=[common], help="update one product")
    p.add_argument("id", type=int)
    p = sub.add_parser("category", parents=[common], help="update every product of a category")
    p.add_argument("id", type=int)
    p = sub.add_parser("catalog", parents=[common], help="update the whole catalog")
    p.add_argument(
        "--ids",
        choices=["all", "odd", "even"],
        default="all",
        help="split the work by odd or even product id",
    )
    sub.add_parser("resume", parents=[common], help="run the catalog again, skipping what is done")
    sub.add_parser("failed", parents=[common], help="list the failed products")
    sub.add_parser("retry", parents=[common], help="process the failed products again")
    p = sub.add_parser("recent", parents=[common], help="list the latest updates")
    p.add_argument("--limit", type=int, default=None)
    p = sub.add_parser("restore", parents=[common], help="put a product back to its saved original")
    p.add_argument("id", type=int)
    sub.add_parser("check", parents=[common], help="check the configuration and connections")
    return parser


def setup_logging(settings):
    handlers = [logging.StreamHandler(sys.stderr)]
    if settings.log_file:
        handlers.append(logging.FileHandler(settings.log_file))
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )
    # One INFO line per HTTP request would drown the progress lines. The OpenAI SDK ships its own
    # HTTP client under the names httpx2 / httpcore2, so naming only httpx and httpcore is not enough.
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def run(argv, settings, runtime=None, out=print):
    args = build_parser().parse_args(argv)
    args.command = args.command or "menu"
    runtime = runtime or Runtime(settings)
    try:
        return await COMMANDS[args.command](runtime, args, out)
    finally:
        await runtime.close()


def main(argv=None):
    settings = Settings()
    setup_logging(settings)
    try:
        return asyncio.run(run(argv, settings))
    except ConfigError as error:
        print(f"{error}. See .env.example.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
