import httpx
import pytest

from epiphany.woo import WooClient, WooError


def make(handler, attempts=3, sleeps=None):
    async def sleep(seconds):
        if sleeps is not None:
            sleeps.append(seconds)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), auth=httpx.BasicAuth("ck_demo", "cs_demo")
    )
    return WooClient(
        "https://shop.example/", "ck_demo", "cs_demo", attempts=attempts, client=client, sleep=sleep
    )


def json_response(data, status=200, headers=None):
    return httpx.Response(status, json=data, headers=headers)


async def test_requests_go_to_the_v3_api_with_basic_auth_and_no_keys_in_the_url():
    seen = []

    def handler(request):
        seen.append(request)
        return json_response({"id": 5, "name": "X"})

    assert await make(handler).get_product(5) == {"id": 5, "name": "X"}
    request = seen[0]
    assert str(request.url) == "https://shop.example/wp-json/wc/v3/products/5"
    assert request.headers["Authorization"].startswith("Basic ")
    assert "ck_demo" not in str(request.url) and "consumer_key" not in str(request.url)


async def test_a_missing_product_or_category_is_none():
    assert await make(lambda r: json_response({"code": "x"}, 404)).get_product(1) is None
    assert await make(lambda r: json_response({"code": "x"}, 404)).get_category(1) is None


async def test_a_server_error_is_retried_with_a_growing_delay_then_succeeds():
    answers = iter([503, 502, 200])
    sleeps = []

    def handler(request):
        status = next(answers)
        return json_response({"id": 1} if status == 200 else {}, status)

    assert await make(handler, attempts=5, sleeps=sleeps).get_product(1) == {"id": 1}
    assert sleeps == [0.3, 0.6]


async def test_retry_after_is_honoured_for_429():
    answers = iter([429, 200])
    sleeps = []

    def handler(request):
        return json_response(
            {"id": 1}, next(answers), {"Retry-After": "7"} if len(sleeps) == 0 else None
        )

    await make(handler, sleeps=sleeps).get_product(1)
    assert sleeps == [7]


async def test_it_gives_up_after_the_attempts_without_leaking_credentials():
    calls = []

    def handler(request):
        calls.append(1)
        return json_response({}, 500)

    with pytest.raises(WooError) as caught:
        await make(handler, attempts=3).get_product(1)
    assert len(calls) == 3 and caught.value.status == 500
    assert "ck_demo" not in str(caught.value) and "cs_demo" not in str(caught.value)


async def test_timeouts_and_disconnects_are_retried():
    answers = iter(["timeout", "disconnect", "ok"])

    def handler(request):
        step = next(answers)
        if step == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        if step == "disconnect":
            raise httpx.RemoteProtocolError("closed", request=request)
        return json_response({"id": 9})

    assert await make(handler, attempts=3).get_product(9) == {"id": 9}


async def test_a_client_error_is_an_error_with_woocommerces_own_message():
    with pytest.raises(WooError) as caught:
        await make(
            lambda r: json_response(
                {
                    "code": "woocommerce_rest_cannot_view",
                    "message": "Sorry, you cannot list resources.",
                },
                401,
            )
        ).get_product(1)
    assert caught.value.status == 401 and "Sorry, you cannot list resources." in str(caught.value)


async def test_a_client_error_that_is_not_json():
    with pytest.raises(WooError, match="502|403"):
        await make(lambda r: httpx.Response(403, text="<html>Forbidden</html>")).get_product(1)


async def test_categories_are_fetched_page_after_page():
    """WooCommerce returns 10 categories unless told otherwise; the old code never asked for more."""
    pages = {1: [{"id": i} for i in range(100)], 2: [{"id": i} for i in range(100, 105)]}
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return json_response(pages[int(request.url.params["page"])])

    found = await make(handler).categories()
    assert (
        len(found) == 105
        and seen[0]["per_page"] == "100"
        and [s["page"] for s in seen] == ["1", "2"]
    )


async def test_exactly_a_full_last_page_ends_on_an_empty_page():
    pages = {1: [{"id": i} for i in range(100)], 2: []}
    found = await make(lambda r: json_response(pages[int(r.url.params["page"])])).categories()
    assert len(found) == 100


async def test_products_come_in_pages_until_a_short_or_empty_page_and_filter_by_category():
    pages = {1: [{"id": 1}, {"id": 2}], 2: [{"id": 3}, {"id": 4}], 3: []}
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return json_response(pages[int(request.url.params["page"])])

    batches = [b async for b in make(handler).products(category=44, per_page=2)]
    assert [[p["id"] for p in b] for b in batches] == [[1, 2], [3, 4]]
    assert all(s["category"] == "44" and s["per_page"] == "2" for s in seen) and len(seen) == 3


async def test_products_without_a_category_send_no_category_parameter():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return json_response([{"id": 1}])

    [b async for b in make(handler).products(per_page=5)]
    assert "category" not in seen[0]


async def test_a_category_run_ends_even_when_the_stores_count_is_too_high():
    """The old loop waited for `count` products and never ended when the count was wrong."""
    pages = {1: [{"id": 1}], 2: []}
    batches = [
        b
        async for b in make(lambda r: json_response(pages[int(r.url.params["page"])])).products(
            category=1, per_page=1
        )
    ]
    assert batches == [[{"id": 1}]]


async def test_update_sends_a_put_with_the_payload_and_returns_the_product():
    seen = []

    def handler(request):
        seen.append(request)
        return json_response({"id": 3, "permalink": "https://shop.example/p/3"})

    result = await make(handler).update_product(3, {"name": "N"})
    assert result["permalink"] == "https://shop.example/p/3"
    assert seen[0].method == "PUT" and seen[0].url.path == "/wp-json/wc/v3/products/3"
    assert seen[0].content == b'{"name":"N"}'


async def test_a_rejected_update_is_an_error():
    with pytest.raises(WooError, match="400.*invalid"):
        await make(lambda r: json_response({"message": "invalid"}, 400)).update_product(3, {})


async def test_close_closes_the_http_client():
    client = make(lambda r: json_response({}))
    await client.close()
    assert client.client.is_closed
