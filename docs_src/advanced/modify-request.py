from collections.abc import Generator
from typing import Any

import httpx
from httpx import Request

from fastapi_proxy_lib.fastapi.app import reverse_http_app


class MyCustomAuth(httpx.Auth):
    # ref: https://www.python-httpx.org/advanced/#customizing-authentication

    def __init__(self, token: str):
        self.token = token

    def auth_flow(self, request: httpx.Request) -> Generator[Request, Any, None]:
        # Send the request, with a custom `X-Authentication` header.
        request.headers["X-Authentication"] = self.token
        yield request


app = reverse_http_app(
    client=httpx.AsyncClient(auth=MyCustomAuth("bearer_token")),
    base_url="http://www.httpbin.org/",
)
