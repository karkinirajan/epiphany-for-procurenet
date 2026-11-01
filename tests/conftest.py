import os
import uuid

import psycopg
import pytest

from epiphany.config import Settings
from epiphany.content import LongContent, ShortContent
from epiphany.db import Store

# The tests must never read a developer's real .env.
Settings.model_config["env_file"] = None


# ------------------------------------------------------------------------------------- fakes
class FakeWoo:
    """The same methods as WooClient, over a dictionary."""

    def __init__(self, products=None, categories=None):
        self.products_by_id = {p["id"]: dict(p) for p in (products or [])}
        self.category_list = (
            categories
            if categories is not None
            else [
                {"id": 10, "name": "Solvents"},
                {"id": 11, "name": "Acids"},
                {"id": 12, "name": "Bases"},
                {"id": 13, "name": "Salts"},
            ]
        )
        self.updates = []
        self.category_calls = 0
        self.fail_update = set()
        self.closed = False

    async def get_product(self, product_id):
        return self.products_by_id.get(int(product_id))

    async def get_category(self, category_id):
        return next((c for c in self.category_list if c["id"] == int(category_id)), None)

    async def categories(self):
        self.category_calls += 1
        return self.category_list

    async def products(self, category=None, per_page=100):
        items = [
            p for p in self.products_by_id.values()
            if category is None or category in p.get("category_ids", [])
        ]  # fmt: skip
        for start in range(0, len(items), per_page):
            yield items[start : start + per_page]

    async def update_product(self, product_id, payload):
        if product_id in self.fail_update:
            from epiphany.woo import WooError

            raise WooError("WooCommerce answered 400: invalid payload", 400)
        self.updates.append((product_id, payload))
        product = self.products_by_id.setdefault(product_id, {"id": product_id})
        product.update(
            {k: v for k, v in payload.items() if k in ("name", "short_description", "description")}
        )
        return {**product, "permalink": f"https://shop.example/p/{product_id}"}

    async def close(self):
        self.closed = True


class FakeGenerator:
    def __init__(self, categories=(10, 11), seo_title="Acetone 99% | Solvent", fail_for=()):
        self.categories, self.seo_title, self.fail_for = list(categories), seo_title, set(fail_for)
        self.short_calls, self.long_calls = [], []
        self.in_flight = self.max_in_flight = 0

    async def short(self, title, short_description, categories_string):
        import asyncio

        from epiphany.ai import GenerationError

        self.short_calls.append((title, short_description, categories_string))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            if title in self.fail_for:
                raise GenerationError("no usable short description from the model: demo")
            return ShortContent(
                short_description=f"<ul><li><strong>{title}</strong></li></ul>",
                categories=self.categories,
            )
        finally:
            self.in_flight -= 1

    async def long(self, title, long_description):
        self.long_calls.append((title, long_description))
        return LongContent(
            long_description=f"<p>About {title}</p>",
            seo_title=self.seo_title,
            meta_description="Buy it here",
            focus_keyword="acetone",
            tags=["solvent", "acetone"],
        )


class FakeStore:
    """The same methods as Store, in memory."""

    def __init__(self):
        self.updated, self.failed_rows, self.generated, self.originals = {}, {}, {}, {}
        self.closed = False

    async def is_updated(self, product_id):
        return product_id in self.updated

    async def mark_updated(self, product_id, name, url):
        self.updated[product_id] = (name, url)

    async def unmark_updated(self, product_id):
        self.updated.pop(product_id, None)

    async def mark_failed(self, product_id, name, url, error):
        self.failed_rows[product_id] = (name, url, error)

    async def clear_failed(self, product_id):
        self.failed_rows.pop(product_id, None)

    async def failed(self):
        return [(i, n, u, e) for i, (n, u, e) in sorted(self.failed_rows.items())]

    async def recent_updates(self, limit=None):
        rows = [(i, n, u, "2026-11-01 10:00") for i, (n, u) in self.updated.items()]
        return rows[:limit] if limit else rows

    async def save_generated(
        self, product_id, short, long_, seo_title, meta, focus, tags, categories
    ):
        self.generated[product_id] = (short, long_, seo_title, meta, focus, tags, categories)

    async def save_original(self, product_id, name, short_description, description):
        self.originals.setdefault(product_id, (name, short_description, description))

    async def original(self, product_id):
        return self.originals.get(product_id)

    async def close(self):
        self.closed = True


def product(product_id, name=None, **extra):
    return {
        "id": product_id,
        "name": name or f"Product {product_id}",
        "short_description": f"short {product_id}",
        "description": f"long {product_id}",
        "permalink": f"https://shop.example/p/{product_id}",
        **extra,
    }


@pytest.fixture
def woo():
    return FakeWoo([product(i) for i in range(1, 7)])


@pytest.fixture
def generator():
    return FakeGenerator()


@pytest.fixture
def store():
    return FakeStore()


# ------------------------------------------------------------------------- a real PostgreSQL
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture
async def pg():
    """A Store on a throwaway schema of the PostgreSQL in TEST_DATABASE_URL (skipped without it)."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    schema = "t_" + uuid.uuid4().hex[:12]
    admin = await psycopg.AsyncConnection.connect(TEST_DATABASE_URL, autocommit=True)
    await admin.execute(f"CREATE SCHEMA {schema}")
    connection = await psycopg.AsyncConnection.connect(TEST_DATABASE_URL, autocommit=True)
    await connection.execute(f"SET search_path TO {schema}")
    store = Store(connection)
    yield store, schema, connection
    await connection.close()
    await admin.execute(f"DROP SCHEMA {schema} CASCADE")
    await admin.close()
