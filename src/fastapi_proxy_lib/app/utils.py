"""User-oriented helper functions.

Note: All user-oriented non-private functions (including local functions) must have documentation.
"""

import asyncio
import warnings
from contextlib import asynccontextmanager
from typing import (
    Any,
    AsyncContextManager,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Literal,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
)

import httpx
from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response
from starlette.websockets import WebSocket
from typing_extensions import deprecated, overload

from fastapi_proxy_lib.core.http import ForwardHttpProxy, ReverseHttpProxy
from fastapi_proxy_lib.core.websocket import ReverseWebSocketProxy

_HttpProxyTypes = Union[ForwardHttpProxy, ReverseHttpProxy]
_WebSocketProxyTypes = ReverseWebSocketProxy


_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_LifeEventTypes = Callable[[_T_co], Awaitable[None]]
_APIRouterTypes = TypeVar("_APIRouterTypes", bound=APIRouter)


_HttpMethodTypes = Tuple[
    Literal["get"],
    Literal["post"],
    Literal["put"],
    Literal["delete"],
    Literal["options"],
    Literal["head"],
    Literal["patch"],
    Literal["trace"],
]
HTTP_METHODS: _HttpMethodTypes = (
    "get",
    "post",
    "put",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
)


# https://fastapi.tiangolo.com/zh/advanced/events/
@deprecated(
    "May or may not be removed in the future.", category=PendingDeprecationWarning
)
def lifespan_event_factory(
    *,
    startup_events: Optional[Iterable[_LifeEventTypes[_T]]] = None,
    shutdown_events: Optional[Iterable[_LifeEventTypes[_T]]] = None,
) -> Callable[[_T], AsyncContextManager[None]]:
    """Create lifespan event for app.

    When the app startup, await all the startup events.
    When the app shutdown, await all the shutdown events.

    The `app` will pass into the event as the first argument.

    Args:
        startup_events:
            An iterable container,
            where each element is an asynchronous function
            which needs to accept first positional parameter for `app`.
        shutdown_events:
            The same as `startup_events`.

    Returns:
        app lifespan event.
    """

    @asynccontextmanager
    async def lifespan(app: _T) -> AsyncIterator[None]:
        if startup_events is not None:
            await asyncio.gather(*[event(app) for event in startup_events])
        yield
        if shutdown_events is not None:
            await asyncio.gather(*[event(app) for event in shutdown_events])

    return lifespan


def _http_register_router(
    proxy: _HttpProxyTypes,
    router: APIRouter,
    **kwargs: Any,
) -> None:
    """Bind http proxy to router.

    Args:
        proxy: http proxy to bind.
        router: fastapi router to bind.
        **kwargs: The kwargs to pass to router endpoint(e.g `router.get()`).

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
        **kwargs: The kwargs to pass to router endpoint(e.g `router.websocket()`).

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
            If the establish websocket connection failed, return a JSONResponse.
            If the establish websocket connection success, will run forever until the connection is closed. Then return False.
        """
        return await proxy.proxy(websocket=websocket, path=path)


class RouterHelper:
    """Helper class to register proxy to fastapi router."""

    def __init__(self) -> None:
        """Initialize RouterHelper."""
        self._registered_clients: Set[httpx.AsyncClient] = set()
        self._registered_router_id: Set[int] = set()

    @property
    def registered_clients(self) -> Set[httpx.AsyncClient]:
        """The httpx.AsyncClient that has been registered."""
        return self._registered_clients

    @overload
    def register_router(
        self,
        proxy: Union[_HttpProxyTypes, _WebSocketProxyTypes],
        router: Optional[None] = None,
        **endpoint_kwargs: Any,
    ) -> APIRouter:
        """If router is None, will create a new router."""

    @overload
    def register_router(
        self,
        proxy: Union[_HttpProxyTypes, _WebSocketProxyTypes],
        router: _APIRouterTypes,
        **endpoint_kwargs: Any,
    ) -> _APIRouterTypes:
        """If router is not None, will use the given router."""

    def register_router(
        self,
        proxy: Union[_HttpProxyTypes, _WebSocketProxyTypes],
        router: Optional[APIRouter] = None,
        **endpoint_kwargs: Any,
    ) -> APIRouter:
        """Register proxy to router.

        Args:
            proxy: The http/websocket proxy to register.
            router: The fastapi router to register.
                If None, will create a new router.
                Usually, you don't need to set the argument, unless you want set some arguments to router.
                Note: the same router can only be registered once.
            **endpoint_kwargs: The kwargs to pass to router endpoint(e.g `router.get()`).

        Raises:
            TypeError: If pass a unknown proxy type.

        Returns:
            A fastapi router, which proxy endpoint has been registered on root route: '/'.
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
        self._registered_clients.add(proxy.client)
        return router

    def get_lifespan(self) -> Callable[..., AsyncContextManager[None]]:
        """The lifespan event for closing registered clients.

        Returns:
            asynccontextmanager for closing registered clients.
        """

        @asynccontextmanager
        async def shutdown_clients(*_: Any, **__: Any) -> AsyncIterator[None]:
            """Asynccontextmanager for closing registered clients.

            Args:
                *_: Whatever.
                **__: Whatever.

            Returns:
                When __aexit__ is called, will close all registered clients.
            """
            yield
            await asyncio.gather(
                *[client.aclose() for client in self.registered_clients]
            )

        return shutdown_clients
