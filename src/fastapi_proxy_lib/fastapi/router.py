"""Utils for registering proxy to fastapi router.

The low-level API for [fastapi_proxy_lib.fastapi.app][].
"""

import asyncio
import warnings
from contextlib import asynccontextmanager
from typing import (
    Any,
    AsyncContextManager,
    AsyncIterator,
    Callable,
    Literal,
    Optional,
    Set,
    TypeVar,
    Union,
)

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response
from starlette.websockets import WebSocket
from typing_extensions import overload

from fastapi_proxy_lib.core.http import ForwardHttpProxy, ReverseHttpProxy
from fastapi_proxy_lib.core.websocket import ReverseWebSocketProxy

__all__ = ("RouterHelper",)


_HttpProxyTypes = Union[ForwardHttpProxy, ReverseHttpProxy]
_WebSocketProxyTypes = ReverseWebSocketProxy


_APIRouterTypes = TypeVar("_APIRouterTypes", bound=APIRouter)


def _http_register_router(
    proxy: _HttpProxyTypes,
    router: APIRouter,
    **kwargs: Any,
) -> None:
    """Bind http proxy to router.

    Args:
        proxy: http proxy to bind.
        router: fastapi router to bind.
        **kwargs: The kwargs to pass to router endpoint(e.g `@router.get()`).

    Returns:
        None. Just do binding proxy to router.
    """
    kwargs.pop("path", None)

    @router.get("/{path:path}", **kwargs)
    @router.post("/{path:path}", **kwargs)
    @router.put("/{path:path}", **kwargs)
    @router.delete("/{path:path}", **kwargs)
    @router.options("/{path:path}", **kwargs)
    @router.head("/{path:path}", **kwargs)
    @router.patch("/{path:path}", **kwargs)
    @router.trace("/{path:path}", **kwargs)
    async def http_proxy(  # pyright: ignore[reportUnusedFunction]
        request: Request, path: str = ""
    ) -> Response:
        """HTTP proxy endpoint.

        Args:
            request: The original request from client.
            path: The path parameters of request.

        Returns:
            The response from target server.
        """
        return await proxy.proxy(request=request, path=path)


def _ws_register_router(
    proxy: _WebSocketProxyTypes,
    router: APIRouter,
    **kwargs: Any,
) -> None:
    """Bind websocket proxy to router.

    Args:
        proxy: websocket proxy to bind.
        router: fastapi router to bind.
        **kwargs: The kwargs to pass to router endpoint(e.g `@router.websocket()`).

    Returns:
        None. Just do binding proxy to router.
    """
    kwargs.pop("path", None)

    @router.websocket("/{path:path}", **kwargs)
    async def ws_proxy(  # pyright: ignore[reportUnusedFunction]
        websocket: WebSocket, path: str = ""
    ) -> Union[Response, Literal[False]]:
        """WebSocket proxy endpoint.

        Args:
            websocket: The original websocket request from client.
            path: The path parameters of request.

        Returns:
            If the establish websocket connection unsuccessfully:
                - Will call `websocket.close()` to send code `4xx`
                - Then return a `StarletteResponse` from target server
            If the establish websocket connection successfully:
                - Will run forever until the connection is closed. Then return False.
        """
        return await proxy.proxy(websocket=websocket, path=path)


class RouterHelper:
    """Helper class to register proxy to fastapi router.

    # # Examples

    ```python
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
    ```

    1. You can pass any arguments to [`APIRouter()`][fastapi.APIRouter] if you want.
    2. Or, with default values, `RouterHelper` will create a new router for you.
    3. Registering a lifespan event to close all proxies is a recommended action.
    4. You can use the proxy router just like a normal `APIRouter`.

    Info:
        Technically, [fastapi_proxy_lib.fastapi.app][] does the same thing,
        including automatically registering lifespan events.

    Abstract: Compared to using the proxy base-class directly, the advantages of using `RouterHelper` are:
        - `RouterHelper` automatically registers all HTTP methods (e.g. `GET`, `POST`, etc.) for you.
            It also registers WebSocket endpoint if you pass in a WebSocket proxy class.
        - Conveniently get the `lifespan` for close all proxies by using `helper.get_lifespan()`.
    """

    def __init__(self) -> None:
        """Initialize RouterHelper."""
        self._registered_proxy: Set[
            Union[_HttpProxyTypes, _WebSocketProxyTypes]
        ] = set()
        self._registered_router_id: Set[int] = set()

    @property
    def registered_proxy(self) -> Set[Union[_HttpProxyTypes, _WebSocketProxyTypes]]:
        """The proxy that has been registered."""
        return self._registered_proxy

    @overload
    def register_router(
        self,
        proxy: Union[_HttpProxyTypes, _WebSocketProxyTypes],
        router: Optional[None] = None,
        **endpoint_kwargs: Any,
    ) -> APIRouter:
        # If router is None, will create a new router.
        ...

    @overload
    def register_router(
        self,
        proxy: Union[_HttpProxyTypes, _WebSocketProxyTypes],
        router: _APIRouterTypes,
        **endpoint_kwargs: Any,
    ) -> _APIRouterTypes:
        # If router is not None, will use the given router.
        ...

    def register_router(
        self,
        proxy: Union[_HttpProxyTypes, _WebSocketProxyTypes],
        router: Optional[APIRouter] = None,
        **endpoint_kwargs: Any,
    ) -> APIRouter:
        """Register proxy to router.

        Args:
            proxy: The `http`/`websocket` proxy to register.
            router: The fastapi router to register. If None, will create a new router.<br>
                Usually, you don't need to set the argument, unless you want set some arguments to router.<br>
                **Note: the same router can only be registered once**.
            **endpoint_kwargs: The kwargs which is passed to router endpoint, e.g:
                - [`@router.get(**endpoint_kwargs)`][fastapi.APIRouter.get]
                - [`@router.websocket(**endpoint_kwargs)`][fastapi.APIRouter.websocket]

        Raises:
            TypeError: If pass a unknown type of `proxy` arg.

        Returns:
            A [fastapi router][fastapi.APIRouter], which proxy endpoint has been registered on root route: `'/'`.
        """
        router = APIRouter() if router is None else router

        # 检查传入的 router 是否已经被注册过，因为 router 不能hash，所以只能用id来判断
        # HACK: 如果之前记录的router已经被销毁了，新的router可能会有相同的id
        router_id = id(router)
        if id(router) in self._registered_router_id:
            msg = (
                f"The router {router} (id: {router_id}) has been registered, "
                f"\033[33myou should not use it to register again in any case\033[m."
            )
            warnings.warn(msg, stacklevel=2)
        else:
            self._registered_router_id.add(router_id)

        if isinstance(proxy, (ForwardHttpProxy, ReverseHttpProxy)):
            _http_register_router(proxy, router, **endpoint_kwargs)
        elif isinstance(
            proxy, ReverseWebSocketProxy
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            _ws_register_router(proxy, router, **endpoint_kwargs)
        else:
            msg = (
                f"Unknown proxy type: {type(proxy)}, "
                f"only support: {_HttpProxyTypes} and {_WebSocketProxyTypes}"
            )
            raise TypeError(msg)

        self._registered_proxy.add(proxy)
        return router

    def get_lifespan(self) -> Callable[..., AsyncContextManager[None]]:
        """The lifespan event for closing registered proxy.

        Returns:
            asynccontextmanager for closing registered proxy,
                refer to [lifespan](https://fastapi.tiangolo.com/advanced/events/#lifespan)
        """

        @asynccontextmanager
        async def shutdown_clients(*_: Any, **__: Any) -> AsyncIterator[None]:
            """Asynccontextmanager for closing registered proxy.

            Args:
                *_: Whatever.
                **__: Whatever.

            Returns:
                When __aexit__ is called, will close all registered proxy.
            """
            yield
            await asyncio.gather(*[proxy.aclose() for proxy in self.registered_proxy])

        return shutdown_clients
