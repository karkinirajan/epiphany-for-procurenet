import asyncio

import psycopg

SCHEMA = [
    # the two tables the old script created
    """CREATE TABLE IF NOT EXISTS updated_products (
        id INTEGER PRIMARY KEY,
        last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        product_name TEXT,
        product_url TEXT,
        retry_failed BOOLEAN DEFAULT FALSE)""",
    """CREATE TABLE IF NOT EXISTS failed_products (
        id INTEGER PRIMARY KEY,
        product_name TEXT,
        product_url TEXT)""",
    # the old INSERT used columns this table was never created with, so failures were never saved
    "ALTER TABLE failed_products ADD COLUMN IF NOT EXISTS error TEXT",
    "ALTER TABLE failed_products ADD COLUMN IF NOT EXISTS failed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    # written to by the old script but never created by it
    """CREATE TABLE IF NOT EXISTS generated_responses (
        id INTEGER PRIMARY KEY,
        short_description TEXT,
        long_description TEXT,
        seo_title TEXT,
        seo_meta_description TEXT,
        focus_keywords TEXT,
        tags TEXT[],
        categories INTEGER[])""",
    # new: the listing as it was before the first rewrite, so a rewrite can be undone
    """CREATE TABLE IF NOT EXISTS original_content (
        id INTEGER PRIMARY KEY,
        name TEXT,
        short_description TEXT,
        description TEXT,
        saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
]


class Store:
    """The PostgreSQL side. One autocommit connection, used one statement at a time (the old
    script shared a plain connection between concurrent tasks and rolled back by hand)."""

    def __init__(self, connection):
        self.connection = connection
        self.lock = asyncio.Lock()

    @classmethod
    async def connect(cls, url):
        connection = await psycopg.AsyncConnection.connect(url, autocommit=True)
        store = cls(connection)
        await store.create_schema()
        return store

    async def close(self):
        await self.connection.close()

    async def _run(self, sql, params=None, fetch=False):
        async with self.lock:
            cursor = await self.connection.execute(sql, params)
            return await cursor.fetchall() if fetch else None

    async def create_schema(self):
        for statement in SCHEMA:
            await self._run(statement)

    async def is_updated(self, product_id):
        rows = await self._run(
            "SELECT 1 FROM updated_products WHERE id = %s", (product_id,), fetch=True
        )
        return bool(rows)

    async def mark_updated(self, product_id, name, url):
        await self._run(
            """INSERT INTO updated_products (id, product_name, product_url)
               VALUES (%s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET product_name = EXCLUDED.product_name,
                   product_url = EXCLUDED.product_url, last_update = CURRENT_TIMESTAMP,
                   retry_failed = FALSE""",
            (product_id, name, url),
        )

    async def unmark_updated(self, product_id):
        await self._run("DELETE FROM updated_products WHERE id = %s", (product_id,))

    async def mark_failed(self, product_id, name, url, error):
        await self._run(
            """INSERT INTO failed_products (id, product_name, product_url, error)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET product_name = EXCLUDED.product_name,
                   product_url = EXCLUDED.product_url, error = EXCLUDED.error,
                   failed_at = CURRENT_TIMESTAMP""",
            (product_id, name, url, error),
        )

    async def clear_failed(self, product_id):
        await self._run("DELETE FROM failed_products WHERE id = %s", (product_id,))

    async def failed(self):
        return await self._run(
            "SELECT id, product_name, product_url, error FROM failed_products ORDER BY id",
            fetch=True,
        )

    async def recent_updates(self, limit=None):
        sql = "SELECT id, product_name, product_url, last_update FROM updated_products ORDER BY last_update DESC"
        if limit:
            return await self._run(sql + " LIMIT %s", (limit,), fetch=True)
        return await self._run(sql, fetch=True)

    async def save_generated(
        self, product_id, short, long_, seo_title, meta, focus, tags, categories
    ):
        await self._run(
            """INSERT INTO generated_responses (id, short_description, long_description, seo_title,
                   seo_meta_description, focus_keywords, tags, categories)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET short_description = EXCLUDED.short_description,
                   long_description = EXCLUDED.long_description, seo_title = EXCLUDED.seo_title,
                   seo_meta_description = EXCLUDED.seo_meta_description,
                   focus_keywords = EXCLUDED.focus_keywords, tags = EXCLUDED.tags,
                   categories = EXCLUDED.categories""",
            (product_id, short, long_, seo_title, meta, focus, tags, categories),
        )

    async def save_original(self, product_id, name, short_description, description):
        """Only the first call per product counts, so reprocessing never overwrites the true original."""
        await self._run(
            """INSERT INTO original_content (id, name, short_description, description)
               VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
            (product_id, name, short_description, description),
        )

    async def original(self, product_id):
        rows = await self._run(
            "SELECT name, short_description, description FROM original_content WHERE id = %s",
            (product_id,),
            fetch=True,
        )
        return rows[0] if rows else None
