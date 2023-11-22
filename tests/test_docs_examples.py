"""Test examples in code docs."""


def test_forward_http_proxy() -> None:
    """测试 ForwardHttpProxy 中的例子."""
    from contextlib import asynccontextmanager
    from typing import AsyncIterator

    from fastapi import FastAPI, Request
    from fastapi_proxy_lib.core.http import ForwardHttpProxy
    from fastapi_proxy_lib.core.tool import default_proxy_filter
    from httpx import AsyncClient

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
    # visit the app: `http://127.0.0.1:8000/https://www.example.com`
    # you will get the response from `https://www.example.com`


def test_reverse_http_proxy() -> None:
    """测试 ReverseHttpProxy 中的例子."""
    from contextlib import asynccontextmanager
    from typing import AsyncIterator

    from fastapi import FastAPI, Request
    from fastapi_proxy_lib.core.http import ReverseHttpProxy
    from httpx import AsyncClient

    proxy = ReverseHttpProxy(AsyncClient(), base_url="https://www.example.com/")

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
    # visit the app: `http://127.0.0.1:8000/`
    # you will get the response from `https://www.example.com/`


def test_reverse_ws_proxy() -> None:
    """测试 ReverseWebSocketProxy 中的例子."""
    from contextlib import asynccontextmanager
    from typing import AsyncIterator

    from fastapi import FastAPI, WebSocket
    from fastapi_proxy_lib.core.websocket import ReverseWebSocketProxy
    from httpx import AsyncClient

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
    from fastapi_proxy_lib.core.http import ReverseHttpProxy
    from fastapi_proxy_lib.core.websocket import ReverseWebSocketProxy
    from fastapi_proxy_lib.fastapi.router import RouterHelper

    reverse_http_proxy = ReverseHttpProxy(base_url="https://www.example.com/")
    reverse_ws_proxy = ReverseWebSocketProxy(base_url="ws://echo.websocket.events/")

    helper = RouterHelper()

    reverse_http_router = helper.register_router(
        reverse_http_proxy,
        APIRouter(),  # (1)!
    )
    reverse_ws_router = helper.register_router(reverse_ws_proxy)  # (2)!

    app = FastAPI(lifespan=helper.get_lifespan())  # (3)!

    app.include_router(reverse_http_router, prefix="/http")  # (4)!
    app.include_router(reverse_ws_router, prefix="/ws")
