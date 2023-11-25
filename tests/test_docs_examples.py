"""Test examples in code docs."""


def test_forward_http_proxy() -> None:
    """测试 ForwardHttpProxy 中的例子."""
    from contextlib import asynccontextmanager
    from typing import AsyncIterator

    from fastapi import FastAPI
    from fastapi_proxy_lib.core.http import ForwardHttpProxy
    from fastapi_proxy_lib.core.tool import default_proxy_filter
    from httpx import AsyncClient
    from starlette.requests import Request

    proxy = ForwardHttpProxy(AsyncClient(), proxy_filter=default_proxy_filter)

    @asynccontextmanager
    async def close_proxy_event(_: FastAPI) -> AsyncIterator[None]:
        """Close proxy."""
        yield
        await proxy.aclose()

    app = FastAPI(lifespan=close_proxy_event)

    @app.get("/{path:path}")
    async def _(request: Request, path: str = ""):
        return await proxy.proxy(request=request, path=path)

    # Then run shell: `uvicorn <your.py>:app --host http://127.0.0.1:8000 --port 8000`
    # visit the app: `http://127.0.0.1:8000/http://www.example.com`
    # you will get the response from `http://www.example.com`


def test_reverse_http_proxy() -> None:
    """测试 ReverseHttpProxy 中的例子."""
    from contextlib import asynccontextmanager
    from typing import AsyncIterator

    from fastapi import FastAPI
    from fastapi_proxy_lib.core.http import ReverseHttpProxy
    from httpx import AsyncClient
    from starlette.requests import Request

    proxy = ReverseHttpProxy(AsyncClient(), base_url="http://www.example.com/")

    @asynccontextmanager
    async def close_proxy_event(_: FastAPI) -> AsyncIterator[None]:  # (1)!
        """Close proxy."""
        yield
        await proxy.aclose()

    app = FastAPI(lifespan=close_proxy_event)

    @app.get("/{path:path}")  # (2)!
    async def _(request: Request, path: str = ""):
        return await proxy.proxy(request=request, path=path)  # (3)!

    # Then run shell: `uvicorn <your.py>:app --host http://127.0.0.1:8000 --port 8000`
    # visit the app: `http://127.0.0.1:8000/`
    # you will get the response from `http://www.example.com/`

    """ 1. lifespan please refer to [starlette/lifespan](https://www.starlette.io/lifespan/)
    2. `{path:path}` is the key.<br>
        It allows the app to accept all path parameters.<br>
        visit <https://www.starlette.io/routing/#path-parameters> for more info.
    3. !!! info
        In fact, you only need to pass the `request: Request` argument.<br>
        `fastapi_proxy_lib` can automatically get the `path` from `request`.<br>
        Explicitly pointing it out here is just to remind you not to forget to specify `{path:path}`. """


def test_reverse_ws_proxy() -> None:
    """测试 ReverseWebSocketProxy 中的例子."""
    from contextlib import asynccontextmanager
    from typing import AsyncIterator

    from fastapi import FastAPI
    from fastapi_proxy_lib.core.websocket import ReverseWebSocketProxy
    from httpx import AsyncClient
    from starlette.websockets import WebSocket

    proxy = ReverseWebSocketProxy(AsyncClient(), base_url="ws://echo.websocket.events/")

    @asynccontextmanager
    async def close_proxy_event(_: FastAPI) -> AsyncIterator[None]:
        """Close proxy."""
        yield
        await proxy.aclose()

    app = FastAPI(lifespan=close_proxy_event)

    @app.websocket_route("/{path:path}")
    async def _(websocket: WebSocket, path: str = ""):
        return await proxy.proxy(websocket=websocket, path=path)

    # Then run shell: `uvicorn <your.py>:app --host http://127.0.0.1:8000 --port 8000`
    # visit the app: `ws://127.0.0.1:8000/`
    # you can establish websocket connection with `ws://echo.websocket.events`


def test_router_helper() -> None:
    """测试 RouterHelper 中的例子."""
    from fastapi import APIRouter, FastAPI
    from fastapi_proxy_lib.core.http import ForwardHttpProxy, ReverseHttpProxy
    from fastapi_proxy_lib.core.tool import default_proxy_filter
    from fastapi_proxy_lib.core.websocket import ReverseWebSocketProxy
    from fastapi_proxy_lib.fastapi.router import RouterHelper

    reverse_http_proxy = ReverseHttpProxy(base_url="http://www.example.com/")
    reverse_ws_proxy = ReverseWebSocketProxy(base_url="ws://echo.websocket.events/")
    forward_http_proxy = ForwardHttpProxy(proxy_filter=default_proxy_filter)

    helper = RouterHelper()

    reverse_http_router = helper.register_router(
        reverse_http_proxy,
        APIRouter(prefix="/reverse"),  # (1)!
    )
    forward_http_router = helper.register_router(
        forward_http_proxy,
        APIRouter(prefix="/forward"),
    )
    reverse_ws_router = helper.register_router(reverse_ws_proxy)  # (2)!

    app = FastAPI(lifespan=helper.get_lifespan())  # (3)!

    app.include_router(reverse_http_router, prefix="/http")  # (4)!
    app.include_router(forward_http_router, prefix="/http")
    app.include_router(reverse_ws_router, prefix="/ws")

    # reverse http proxy on "/http/reverse"
    # forward http proxy on "/http/forward"
    # reverse websocket proxy on "/ws"

    """ 1. You can pass any arguments to [`APIRouter()`][fastapi.APIRouter] if you want.
    2. Or, with default values, `RouterHelper` will create a new router for you.
    3. Registering a lifespan event to close all proxies is a recommended action.
    4. You can use the proxy router just like a normal `APIRouter`. """
