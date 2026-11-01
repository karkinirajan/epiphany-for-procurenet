import pytest

from epiphany.ai import GenerationError
from epiphany.content import LongContent, ShortContent
from epiphany.pipeline import (
    Updater,
    as_id,
    build_payload,
    fetch_products,
    restore,
    valid_category_ids,
)

from .conftest import FakeGenerator, FakeStore, FakeWoo, product


def short(**kw):
    return ShortContent(**{"short_description": "<p>short</p>", "categories": [], **kw})


def long(**kw):
    return LongContent(**{"long_description": "<p>long</p>", **kw})


# ---------------------------------------------------------------------------------- payload
def test_the_payload_has_the_cleaned_descriptions_name_tags_categories_and_yoast_fields():
    payload = build_payload(
        short(short_description="<p onclick='x()'>s</p><script>1</script>", categories=[]),
        long(seo_title="SEO", meta_description="meta", focus_keyword="kw", tags=["a", "b"]),
        [10, 11],
    )
    assert payload["short_description"] == "<p>s</p>" and payload["description"] == "<p>long</p>"
    assert payload["name"] == "SEO"
    assert payload["tags"] == [{"name": "a"}, {"name": "b"}]
    assert payload["categories"] == [{"id": 10}, {"id": 11}]
    assert payload["meta_data"] == [
        {"key": "_yoast_wpseo_metadesc", "value": "meta"},
        {"key": "_yoast_wpseo_title", "value": "SEO"},
        {"key": "_yoast_wpseo_focuskw", "value": "kw"},
    ]


def test_no_categories_means_the_key_is_absent_not_an_empty_list():
    """An empty list tells WooCommerce to remove every category of the product."""
    assert "categories" not in build_payload(short(), long(), [])


def test_an_empty_seo_title_never_blanks_the_product_name():
    payload = build_payload(short(), long(seo_title=""), [])
    assert "name" not in payload


def test_the_rename_can_be_switched_off_but_the_yoast_title_is_still_set():
    payload = build_payload(short(), long(seo_title="SEO"), [], rename=False)
    assert "name" not in payload
    assert {"key": "_yoast_wpseo_title", "value": "SEO"} in payload["meta_data"]


def test_empty_yoast_fields_and_tags_are_not_sent_so_existing_ones_are_kept():
    payload = build_payload(
        short(), long(seo_title="", meta_description="", focus_keyword="", tags=[]), []
    )
    assert payload["meta_data"] == [] and "tags" not in payload


@pytest.mark.parametrize(
    "bad", [short(short_description="<script>x()</script>"), short(short_description="  ")]
)
def test_a_description_that_is_empty_after_cleaning_is_refused(bad):
    with pytest.raises(GenerationError, match="empty description"):
        build_payload(bad, long(), [])
    with pytest.raises(GenerationError, match="empty description"):
        build_payload(short(), long(long_description="<iframe src=x></iframe>"), [])


# --------------------------------------------------------------------------------- categories
CATS = [{"id": 10}, {"id": 11}, {"id": 12}, {"id": 13}]


def test_only_existing_categories_are_kept_without_duplicates_at_most_three():
    assert valid_category_ids([99, 10, 10, 11, 12, 13], CATS) == [10, 11, 12]
    assert valid_category_ids([99, 100], CATS) == []
    assert valid_category_ids([], CATS) == []


@pytest.mark.parametrize(
    ("raw", "expected"), [(5, 5), ("7", 7), (" 8 ", 8), (None, None), ("x", None), ([], None)]
)
def test_as_id(raw, expected):
    assert as_id(raw) == expected


# ------------------------------------------------------------------------------------ process
def updater(woo, generator, store, **kw):
    return Updater(woo, generator, store, **kw)


async def test_a_product_is_generated_updated_and_recorded(woo, generator, store):
    outcome = await updater(woo, generator, store).process(product(3, "Acetone"))
    assert (outcome.status, outcome.url, outcome.product_id) == (
        "updated",
        "https://shop.example/p/3",
        3,
    )
    product_id, payload = woo.updates[0]
    assert product_id == 3 and payload["name"] == "Acetone 99% | Solvent"
    assert payload["categories"] == [{"id": 10}, {"id": 11}]
    assert 3 in store.updated and 3 not in store.failed_rows
    assert store.originals[3] == ("Acetone", "short 3", "long 3")


async def test_the_original_listing_is_saved_before_the_store_is_changed(woo, generator, store):
    order = []
    original_save, original_update = store.save_original, woo.update_product

    async def save(*a):
        order.append("saved")
        await original_save(*a)

    async def update(*a):
        order.append("updated")
        return await original_update(*a)

    store.save_original, woo.update_product = save, update
    await updater(woo, generator, store).process(product(1))
    assert order == ["saved", "updated"]


async def test_the_prompts_get_the_products_text_and_the_category_list(woo, generator, store):
    await updater(woo, generator, store).process(
        product(2, "Acetone", short_description="", description="Old long")
    )
    title, base, categories_string = generator.short_calls[0]
    assert (title, base) == ("Acetone", "No short description available.")
    assert categories_string == "10: Solvents, 11: Acids, 12: Bases, 13: Salts"
    assert generator.long_calls[0] == ("Acetone", "Old long")


async def test_a_product_already_updated_is_skipped_unless_forced(woo, generator, store):
    store.updated[4] = ("n", "u")
    assert (await updater(woo, generator, store).process(product(4))).status == "skipped"
    assert woo.updates == [] and generator.short_calls == []
    assert (
        await updater(woo, generator, store, force=True).process(product(4))
    ).status == "updated"


async def test_a_dry_run_generates_and_saves_the_text_but_changes_nothing_else(
    woo, generator, store
):
    outcome = await updater(woo, generator, store, dry_run=True).process(product(5))
    assert outcome.status == "dry-run"
    assert (
        woo.updates == []
        and store.updated == {}
        and store.originals == {}
        and store.failed_rows == {}
    )
    short_text, long_text, seo_title, meta, focus, tags, categories = store.generated[5]
    assert short_text.startswith("<ul>") and seo_title == "Acetone 99% | Solvent"
    assert tags == ["solvent", "acetone"] and categories == [10, 11]


async def test_a_dry_run_failure_is_reported_but_not_recorded_as_a_failed_product(woo, store):
    generator = FakeGenerator(fail_for={"Product 6"})
    outcome = await updater(woo, generator, store, dry_run=True).process(product(6))
    assert outcome.status == "failed" and store.failed_rows == {}


async def test_a_generation_failure_is_recorded_and_the_store_is_untouched(woo, store):
    generator = FakeGenerator(fail_for={"Product 1"})
    outcome = await updater(woo, generator, store).process(product(1))
    assert outcome.status == "failed" and "GenerationError" in outcome.error
    assert woo.updates == [] and 1 not in store.updated
    name, url, error = store.failed_rows[1]
    assert (
        name == "Product 1"
        and url == "https://shop.example/p/1"
        and "no usable short description" in error
    )


async def test_an_update_failure_keeps_the_generated_text_and_the_real_name_and_url(
    woo, generator, store
):
    woo.fail_update.add(2)
    outcome = await updater(woo, generator, store).process(product(2, "Acetone"))
    assert outcome.status == "failed" and "WooError" in outcome.error
    assert (
        store.failed_rows[2][0] == "Acetone"
    )  # not the literal text "product_name" the old code stored
    assert store.failed_rows[2][1] == "https://shop.example/p/2"  # nor "product_url"
    assert 2 in store.generated and 2 not in store.updated


async def test_a_successful_retry_clears_the_failure(woo, generator, store):
    store.failed_rows[3] = ("n", "u", "old error")
    await updater(woo, generator, store, force=True).process(product(3))
    assert 3 not in store.failed_rows and 3 in store.updated


async def test_a_product_without_a_usable_id_fails_without_touching_anything(woo, generator, store):
    outcome = await updater(woo, generator, store).process({"name": "No id"})
    assert (
        outcome.status == "failed" and outcome.product_id == 0 and "no usable id" in outcome.error
    )
    assert store.failed_rows == {} and woo.updates == []


async def test_a_failure_to_record_a_failure_does_not_hide_the_outcome(woo, store, caplog):
    generator = FakeGenerator(fail_for={"Product 1"})

    async def broken(*a):
        raise RuntimeError("database is down")

    store.mark_failed = broken
    outcome = await updater(woo, generator, store).process(product(1))
    assert outcome.status == "failed" and "Could not record the failure" in caplog.text


async def test_the_categories_are_fetched_once_for_a_whole_run(woo, generator, store):
    await updater(woo, generator, store).run([product(i) for i in range(1, 7)])
    assert woo.category_calls == 1


# ---------------------------------------------------------------------------------------- run
async def test_one_failing_product_does_not_stop_the_others_and_the_report_counts(woo, store):
    generator = FakeGenerator(fail_for={"Product 2"})
    store.updated[5] = ("n", "u")
    report = await updater(woo, generator, store).run([product(i) for i in range(1, 7)])
    assert report.counts == {"updated": 4, "failed": 1, "skipped": 1}
    assert report.summary() == "4 updated, 1 skipped, 1 failed"
    assert [o.product_id for o in report.failed] == [2]


async def test_the_number_of_products_in_flight_is_bounded(woo, store):
    generator = FakeGenerator()
    await updater(woo, generator, store, concurrency=2).run([product(i) for i in range(1, 7)])
    assert generator.max_in_flight == 2


async def test_an_empty_run(woo, generator, store):
    report = await updater(woo, generator, store).run([])
    assert report.summary() == "nothing to do"


async def test_progress_is_logged_for_every_product(woo, generator, store, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="epiphany.pipeline"):
        await updater(woo, generator, store).run([product(1), product(2)])
    assert "[1/2]" in caplog.text and "[2/2]" in caplog.text


# ------------------------------------------------------------------------------ fetch_products
async def test_fetch_products_collects_every_page():
    woo = FakeWoo([product(i) for i in range(1, 8)])
    assert [p["id"] for p in await fetch_products(woo)] == list(range(1, 8))


async def test_fetch_products_by_category_and_parity():
    items = [product(i, category_ids=[1] if i <= 4 else [2]) for i in range(1, 9)]
    woo = FakeWoo(items)
    assert [p["id"] for p in await fetch_products(woo, category=1)] == [1, 2, 3, 4]
    assert [p["id"] for p in await fetch_products(woo, parity="odd")] == [1, 3, 5, 7]
    assert [p["id"] for p in await fetch_products(woo, parity="even")] == [2, 4, 6, 8]


# ---------------------------------------------------------------------------------- restore
async def test_restore_puts_the_original_back_and_allows_a_new_run(woo, generator, store):
    await updater(woo, generator, store).process(product(1, "Acetone"))
    assert woo.products_by_id[1]["name"] == "Acetone 99% | Solvent"
    assert await restore(woo, store, 1) == "Acetone"
    assert woo.updates[-1][1] == {
        "name": "Acetone",
        "short_description": "short 1",
        "description": "long 1",
    }
    assert 1 not in store.updated  # a later catalog run will process it again


async def test_the_first_original_is_kept_when_a_product_is_processed_twice(woo, generator, store):
    runner = updater(woo, generator, store, force=True)
    await runner.process(product(1, "Original name"))
    await runner.process(
        product(1, "Acetone 99% | Solvent")
    )  # now the store shows the rewritten name
    assert store.originals[1][0] == "Original name"


async def test_restore_without_a_saved_original_is_an_error(woo, store):
    with pytest.raises(LookupError, match="no saved original for product 9"):
        await restore(woo, store, 9)


def test_fakes_agree_with_the_real_store_interface():
    """The fakes are only useful while they offer every method the pipeline calls on the Store."""
    from epiphany.db import Store

    public = {n for n in dir(Store) if not n.startswith("_") and callable(getattr(Store, n))}
    missing = (
        public - {n for n in dir(FakeStore) if not n.startswith("_")} - {"connect", "create_schema"}
    )
    assert missing == set(), missing


async def test_failing_to_save_the_generated_text_is_logged_and_does_not_change_the_outcome(
    woo, generator, store, caplog
):
    async def broken(*a):
        raise RuntimeError("disk full")

    store.save_generated = broken
    outcome = await Updater(woo, generator, store, dry_run=True).process(product(1))
    assert (
        outcome.status == "dry-run"
        and "Could not save the generated text of product 1" in caplog.text
    )
