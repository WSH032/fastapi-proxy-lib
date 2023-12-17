# Advanced

For the following scenarios, you might prefer [fastapi_proxy_lib.core][]:

- When you need to use proxies with **only** `Starlette` dependencies (without `FastAPI`).
- When you need more fine-grained control over parameters and lifespan event.
- When you need to further process the input and output before and after the proxy (similar to middleware).

We will demonstrate with `FastAPI`,
but you can completely switch to the `Starlette` approach,
which is officially supported by this project.

## Starlette Support

**^^[Please visit the `ReverseHttpProxy#examples` to view the demo with annotations :material-file-document: ][fastapi_proxy_lib.core.http.ReverseHttpProxy--examples]^^**.

Also (without annotations):

- [`ForwardHttpProxy#examples`][fastapi_proxy_lib.core.http.ForwardHttpProxy--examples]
- [`ReverseWebSocketProxy#examples`][fastapi_proxy_lib.core.websocket.ReverseWebSocketProxy--examples]

## Modify request

In some cases, you may want to make final modifications before sending a request, such as performing behind-the-scenes authentication by modifying the headers of request.

`httpx` provides comprehensive authentication support, and `fastapi-proxy-lib` offers first-class support for `httpx`.

See <https://www.python-httpx.org/advanced/#customizing-authentication>

You can refer following example to implement a simple authentication:

```python
import httpx
from fastapi_proxy_lib.fastapi.app import reverse_http_app


class MyCustomAuth(httpx.Auth):
    # ref: https://www.python-httpx.org/advanced/#customizing-authentication

    def __init__(self, token: str):
        self.token = token

    def auth_flow(self, request: httpx.Request):
        # Send the request, with a custom `X-Authentication` header.
        request.headers["X-Authentication"] = self.token
        yield request


app = reverse_http_app(
    client=httpx.AsyncClient(auth=MyCustomAuth("bearer_token")),
    base_url="http://www.httpbin.org/",
)

```

visit `/headers` to see the result which contains `"X-Authentication": "bearer_token"` header.

## Modify response

In some cases, you may want to make final modifications before return the response to the client, such as transcoding video response streams.

See [issue#15](https://github.com/WSH032/fastapi-proxy-lib/issues/15)

You can refer following example to modify the response:

```python
from contextlib import asynccontextmanager
from typing import AsyncIterable, AsyncIterator, Union

from fastapi import FastAPI
from fastapi_proxy_lib.core.http import ReverseHttpProxy
from starlette.requests import Request
from starlette.responses import StreamingResponse

AsyncContentStream = AsyncIterable[Union[str, bytes]]


proxy = ReverseHttpProxy(base_url="http://www.example.com/")


@asynccontextmanager
async def close_proxy_event(_: FastAPI) -> AsyncIterator[None]:
    """Close proxy."""
    yield
    await proxy.aclose()


app = FastAPI(lifespan=close_proxy_event)


async def new_content(origin_content: AsyncContentStream) -> AsyncContentStream:
    """Fake content processing."""
    async for chunk in origin_content:
        # do some processing with chunk, e.g transcoding,
        # here we just print and return it as an example.
        print(chunk)
        yield chunk


@app.get("/{path:path}")
async def _(request: Request, path: str = ""):
    proxy_response = await proxy.proxy(request=request, path=path)

    if isinstance(proxy_response, StreamingResponse):
        # get the origin content stream
        old_content = proxy_response.body_iterator

        new_resp = StreamingResponse(
            content=new_content(old_content),
            status_code=proxy_response.status_code,
            headers=proxy_response.headers,
            media_type=proxy_response.media_type,
        )
        return new_resp

    return proxy_response

```

visit `/`, you will notice that the response body is printed to the console.
