import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class WooError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class WooClient:
    """The WooCommerce REST API (``/wp-json/wc/v3``).

    Differences from the old code: TLS is verified unless you switch it off in the settings, the
    keys travel in a Basic-auth header (one request put them in the query string), every call is
    retried with a back-off on timeouts, 429 and 5xx, and a 4xx answer is an error carrying
    WooCommerce's own message instead of being parsed as if it were a product."""

    def __init__(
        self,
        base_url,
        key,
        secret,
        *,
        verify=True,
        timeout=60.0,
        attempts=5,
        client=None,
        sleep=asyncio.sleep,
    ):
        self.base = base_url.rstrip("/") + "/wp-json/wc/v3"
        self.attempts, self.sleep = max(1, attempts), sleep
        self.client = client or httpx.AsyncClient(
            auth=httpx.BasicAuth(key, secret), verify=verify, timeout=timeout
        )

    async def close(self):
        await self.client.aclose()

    async def _request(self, method, path, **kwargs):
        last = None
        for attempt in range(self.attempts):
            if attempt:
                await self.sleep(self._delay(attempt, last))
            try:
                response = await self.client.request(method, self.base + path, **kwargs)
            except httpx.TransportError as error:  # timeouts, disconnects, DNS
                last = error
                logger.warning(
                    "%s %s failed (%s), attempt %d", method, path, type(error).__name__, attempt + 1
                )
                continue
            if response.status_code in RETRY_STATUS:
                last = response
                logger.warning(
                    "%s %s answered %d, attempt %d", method, path, response.status_code, attempt + 1
                )
                continue
            return response
        status = last.status_code if isinstance(last, httpx.Response) else None
        raise WooError(f"{method} {path} failed after {self.attempts} attempts", status)

    @staticmethod
    def _delay(attempt, last):
        if isinstance(last, httpx.Response):
            retry_after = last.headers.get("Retry-After", "")
            if retry_after.isdigit():
                return min(int(retry_after), 60)
        return 0.3 * (2 ** (attempt - 1))

    @staticmethod
    def _fail(response):
        try:
            message = response.json().get("message") or response.text[:200]
        except Exception:  # noqa: BLE001 - not JSON
            message = response.text[:200]
        return WooError(
            f"WooCommerce answered {response.status_code}: {message}", response.status_code
        )

    async def _get_json(self, path, **params):
        response = await self._request("GET", path, params=params or None)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise self._fail(response)
        return response.json()

    async def get_product(self, product_id):
        return await self._get_json(f"/products/{product_id}")

    async def get_category(self, category_id):
        return await self._get_json(f"/products/categories/{category_id}")

    async def categories(self):
        """All categories. The old code fetched one page, which WooCommerce limits to 10, so a
        store with more categories never offered (or accepted) the rest."""
        found, page = [], 1
        while True:
            batch = await self._get_json("/products/categories", per_page=100, page=page)
            if not batch:
                return found
            found.extend(batch)
            if len(batch) < 100:
                return found
            page += 1

    async def products(self, category=None, per_page=100):
        """Pages of products until an empty page. The old category loop ran until it had as many
        products as the category's ``count`` and never ended when that count was too high."""
        page = 1
        while True:
            params = {"per_page": per_page, "page": page}
            if category is not None:
                params["category"] = category
            batch = await self._get_json("/products", **params)
            if not batch:
                return
            yield batch
            if len(batch) < per_page:
                return
            page += 1

    async def update_product(self, product_id, payload):
        response = await self._request("PUT", f"/products/{product_id}", json=payload)
        if response.status_code != 200:
            raise self._fail(response)
        return response.json()
