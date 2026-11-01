"""The store against a real PostgreSQL (TEST_DATABASE_URL); each test gets its own schema."""

import asyncio

import pytest

pytestmark = pytest.mark.postgres


async def tables(connection):
    cursor = await connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() ORDER BY 1"
    )
    return [row[0] for row in await cursor.fetchall()]


async def columns(connection, table):
    cursor = await connection.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    )
    return {row[0] for row in await cursor.fetchall()}


async def test_the_schema_creates_every_table_and_can_run_twice(pg):
    store, _, connection = pg
    await store.create_schema()
    await store.create_schema()
    assert await tables(connection) == [
        "failed_products",
        "generated_responses",
        "original_content",
        "updated_products",
    ]


async def test_an_existing_database_from_the_old_script_is_upgraded_without_losing_rows(pg):
    """The old script created these two tables only; its failed_products had no `error` column."""
    store, _, connection = pg
    await connection.execute(
        "CREATE TABLE updated_products (id INTEGER PRIMARY KEY, last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "product_name TEXT, product_url TEXT, retry_failed BOOLEAN DEFAULT FALSE)"
    )
    await connection.execute(
        "CREATE TABLE failed_products (id INTEGER PRIMARY KEY, product_name TEXT, product_url TEXT)"
    )
    await connection.execute(
        "INSERT INTO updated_products (id, product_name, product_url) VALUES (1, 'Old', 'u1')"
    )
    await connection.execute(
        "INSERT INTO failed_products (id, product_name, product_url) VALUES (2, 'Bad', 'u2')"
    )
    await store.create_schema()
    assert {"error", "failed_at"} <= await columns(connection, "failed_products")
    assert await store.is_updated(1)
    assert await store.failed() == [(2, "Bad", "u2", None)]


async def test_updated_products_are_upserted_and_refresh_their_time(pg):
    store, _, connection = pg
    await store.create_schema()
    assert not await store.is_updated(7)
    await store.mark_updated(7, "First", "https://s/1")
    assert await store.is_updated(7)
    await connection.execute("UPDATE updated_products SET last_update = '2020-01-01' WHERE id = 7")
    await store.mark_updated(7, "Second", "https://s/2")
    ((name, url, newer),) = [(n, u, t.year > 2020) for _, n, u, t in await store.recent_updates()]
    assert (name, url, newer) == (
        "Second",
        "https://s/2",
        True,
    )  # the old code never refreshed the time


async def test_recent_updates_are_newest_first_and_can_be_limited(pg):
    store, _, connection = pg
    await store.create_schema()
    for i, day in enumerate(("2024-01-01", "2024-03-01", "2024-02-01"), start=1):
        await store.mark_updated(i, f"P{i}", f"u{i}")
        await connection.execute(
            "UPDATE updated_products SET last_update = %s WHERE id = %s", (day, i)
        )
    assert [r[0] for r in await store.recent_updates()] == [2, 3, 1]
    assert [r[0] for r in await store.recent_updates(limit=2)] == [2, 3]


async def test_a_failed_product_is_stored_with_its_error_and_overwritten_by_a_newer_failure(pg):
    store, _, _ = pg
    await store.create_schema()
    await store.mark_failed(5, "Acetone", "https://s/5", "WooError: 400")
    await store.mark_failed(5, "Acetone", "https://s/5", "TimeoutError: slow")
    assert await store.failed() == [(5, "Acetone", "https://s/5", "TimeoutError: slow")]
    await store.clear_failed(5)
    assert await store.failed() == []


async def test_unmark_updated(pg):
    store, _, _ = pg
    await store.create_schema()
    await store.mark_updated(3, "n", "u")
    await store.unmark_updated(3)
    assert not await store.is_updated(3)


async def test_generated_text_is_stored_with_its_arrays_and_upserted(pg):
    store, _, connection = pg
    await store.create_schema()
    await store.save_generated(4, "<p>s</p>", "<p>l</p>", "T", "M", "K", ["a", "b"], [10, 11])
    await store.save_generated(4, "<p>s2</p>", "<p>l2</p>", "T2", "M2", "K2", ["c"], [12])
    cursor = await connection.execute(
        "SELECT short_description, seo_title, tags, categories FROM generated_responses"
    )
    assert await cursor.fetchall() == [("<p>s2</p>", "T2", ["c"], [12])]


async def test_only_the_first_original_is_kept(pg):
    store, _, _ = pg
    await store.create_schema()
    assert await store.original(8) is None
    await store.save_original(8, "Real original", "short", "long")
    await store.save_original(8, "Rewritten later", "s2", "l2")
    assert await store.original(8) == ("Real original", "short", "long")


async def test_values_with_quotes_and_unicode_are_stored_safely(pg):
    store, _, _ = pg
    await store.create_schema()
    nasty = 'O\'Reilly "x"; DROP TABLE updated_products; -- 化学 🧪'
    await store.mark_failed(1, nasty, "u", nasty)
    assert (await store.failed())[0][1] == nasty
    assert "updated_products" in await tables(pg[2])


async def test_concurrent_use_of_the_one_connection_is_serialised(pg):
    store, _, _ = pg
    await store.create_schema()
    await asyncio.gather(*(store.mark_updated(i, f"P{i}", f"u{i}") for i in range(1, 41)))
    assert len(await store.recent_updates()) == 40


async def test_connect_builds_a_ready_store(monkeypatch):
    import os

    from epiphany.db import Store

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    store = await Store.connect(url)
    try:
        assert await store.failed() is not None
    finally:
        await store.close()
