import asyncio
import logging
import time
from collections import Counter
from dataclasses import dataclass, field

from .ai import GenerationError
from .sanitize import clean_html

logger = logging.getLogger(__name__)

MAX_CATEGORIES = 3  # the prompt asks for "up to three"


@dataclass
class Outcome:
    product_id: int
    name: str | None
    status: str  # updated | failed | skipped | dry-run
    url: str | None = None
    error: str | None = None
    seconds: float = 0.0


@dataclass
class Report:
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def counts(self):
        return Counter(outcome.status for outcome in self.outcomes)

    @property
    def failed(self):
        return [outcome for outcome in self.outcomes if outcome.status == "failed"]

    def summary(self):
        counts = self.counts
        parts = [
            f"{counts[s]} {s}" for s in ("updated", "dry-run", "skipped", "failed") if counts[s]
        ]
        return ", ".join(parts) or "nothing to do"


def as_id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def valid_category_ids(wanted, categories):
    """The model's category ids that really exist in the store, without duplicates, at most three.
    The old code sent whatever came back."""
    known = {category["id"] for category in categories}
    chosen = []
    for category_id in wanted:
        if category_id in known and category_id not in chosen:
            chosen.append(category_id)
    return chosen[:MAX_CATEGORIES]


def build_payload(short, long, category_ids, rename=True):
    """The WooCommerce update. Only fields with something in them are sent: the old code sent an
    empty category list (which removes every category of the product), could set an empty product
    name and overwrote the Yoast fields with empty strings."""
    payload = {
        "short_description": clean_html(short.short_description),
        "description": clean_html(long.long_description),
    }
    if not payload["short_description"] or not payload["description"]:
        raise GenerationError("the model returned an empty description")
    if rename and long.seo_title:
        payload["name"] = long.seo_title
    if long.tags:
        payload["tags"] = [{"name": tag} for tag in long.tags]
    if category_ids:
        payload["categories"] = [{"id": category_id} for category_id in category_ids]
    meta = [
        ("_yoast_wpseo_metadesc", long.meta_description),
        ("_yoast_wpseo_title", long.seo_title),
        ("_yoast_wpseo_focuskw", long.focus_keyword),
    ]
    payload["meta_data"] = [{"key": key, "value": value} for key, value in meta if value]
    return payload


async def fetch_products(woo, category=None, parity="all"):
    """Every product (or every product of a category). ``parity`` splits the work between two
    runs by odd or even id, as the old "odd/even" prompt did."""
    products = []
    async for batch in woo.products(category=category):
        products.extend(batch)
    if parity == "odd":
        products = [p for p in products if p["id"] % 2 == 1]
    elif parity == "even":
        products = [p for p in products if p["id"] % 2 == 0]
    return products


class Updater:
    def __init__(
        self, woo, generator, store, *, dry_run=False, force=False, rename=True, concurrency=5
    ):
        self.woo, self.generator, self.store = woo, generator, store
        self.dry_run, self.force, self.rename = dry_run, force, rename
        self.concurrency = max(1, concurrency)
        self._categories = None
        self._lock = asyncio.Lock()

    async def categories(self):
        """Fetched once per run; the old code fetched them twice for every product."""
        async with self._lock:
            if self._categories is None:
                self._categories = await self.woo.categories()
            return self._categories

    async def _remember(self, product_id, payload, long, category_ids):
        try:
            await self.store.save_generated(
                product_id,
                payload.get("short_description"),
                payload.get("description"),
                long.seo_title,
                long.meta_description,
                long.focus_keyword,
                long.tags,
                category_ids,
            )
        except Exception:  # noqa: BLE001 - keeping a copy must not hide the real outcome
            logger.exception("Could not save the generated text of product %s", product_id)

    async def process(self, product):
        started = time.monotonic()
        product_id = as_id(product.get("id"))
        name = product.get("name")
        payload = long = None
        category_ids = []
        try:
            if product_id is None:
                raise ValueError("the product has no usable id")
            if not self.force and await self.store.is_updated(product_id):
                return Outcome(product_id, name, "skipped")
            categories = await self.categories()
            categories_string = ", ".join(f"{c['id']}: {c['name']}" for c in categories)
            short, long = await asyncio.gather(
                self.generator.short(
                    name,
                    product.get("short_description") or "No short description available.",
                    categories_string,
                ),
                self.generator.long(name, product.get("description") or ""),
            )
            category_ids = valid_category_ids(short.categories, categories)
            payload = build_payload(short, long, category_ids, self.rename)
            if self.dry_run:
                await self._remember(product_id, payload, long, category_ids)
                return Outcome(product_id, name, "dry-run", seconds=time.monotonic() - started)
            await self.store.save_original(
                product_id, name, product.get("short_description"), product.get("description")
            )
            updated = await self.woo.update_product(product_id, payload)
            url = updated.get("permalink")
            await self.store.mark_updated(product_id, updated.get("name") or name, url)
            await self.store.clear_failed(product_id)
            return Outcome(product_id, name, "updated", url, seconds=time.monotonic() - started)
        except Exception as error:  # noqa: BLE001 - one product must never stop the run
            message = f"{type(error).__name__}: {error}"[:2000]
            logger.error("Product %s (%s) failed: %s", product.get("id"), name, message)
            if not self.dry_run and product_id is not None:
                try:
                    await self.store.mark_failed(
                        product_id, name, product.get("permalink"), message
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Could not record the failure of product %s", product_id)
                if payload is not None:
                    await self._remember(product_id, payload, long, category_ids)
            return Outcome(
                product_id or 0, name, "failed", error=message, seconds=time.monotonic() - started
            )

    async def run(self, products):
        products = list(products)
        total = len(products)
        gate = asyncio.Semaphore(self.concurrency)
        finished = 0

        async def one(product):
            nonlocal finished
            async with gate:
                outcome = await self.process(product)
            finished += 1
            logger.info(
                "[%d/%d] %s: %s %s",
                finished,
                total,
                outcome.status,
                outcome.name or outcome.product_id,
                outcome.url or outcome.error or "",
            )
            return outcome

        return Report(list(await asyncio.gather(*(one(p) for p in products))))


async def restore(woo, store, product_id):
    """Put a product back to what it was before its first rewrite, and let a later run process it again."""
    original = await store.original(product_id)
    if original is None:
        raise LookupError(f"no saved original for product {product_id}")
    name, short_description, description = original
    await woo.update_product(
        product_id,
        {
            "name": name or "",
            "short_description": short_description or "",
            "description": description or "",
        },
    )
    await store.unmark_updated(product_id)
    return name
