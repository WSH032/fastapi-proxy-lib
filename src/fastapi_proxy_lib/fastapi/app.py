"""Utils for getting a fastapi proxy app.

The high-level API for [fastapi_proxy_lib.fastapi.router][].
"""

from typing import Optional, Union

import httpx
from fastapi import FastAPI

from fastapi_proxy_lib.core._tool import ProxyFilterProto
from fastapi_proxy_lib.core.http import ForwardHttpProxy, ReverseHttpProxy
from fastapi_proxy_lib.core.websocket import (
    DEFAULT_KEEPALIVE_PING_INTERVAL_SECONDS,
    DEFAULT_KEEPALIVE_PING_TIMEOUT_SECONDS,
    DEFAULT_MAX_MESSAGE_SIZE_BYTES,
    DEFAULT_QUEUE_SIZE,
    ReverseWebSocketProxy,
)

from .router import (
    RouterHelper,
    _HttpProxyTypes,  # pyright: ignore [reportPrivateUsage]  # 允许使用本项目内部的私有成员
    _WebSocketProxyTypes,  # pyright: ignore [reportPrivateUsage]  # 允许使用本项目内部的私有成员
)

__all__ = (
    "forward_http_app",
    "reverse_http_app",
    "reverse_ws_app",
)


def _proxy2app(proxy: Union[_HttpProxyTypes, _WebSocketProxyTypes]) -> FastAPI:
    """Util function to register proxy to FastAPI app."""
    # 注意必须要新实例化一个 RouterHelper ,否则共享 RouterHelper 会导致其他app的客户端被关闭
    helper = RouterHelper()

    router = helper.register_router(proxy)

    app = FastAPI(lifespan=helper.get_lifespan())
    app.include_router(router)

    return app


def forward_http_app(
    client: Optional[httpx.AsyncClient] = None,
    *,
    follow_redirects: bool = False,
    proxy_filter: Optional[ProxyFilterProto] = None,
) -> FastAPI:
    """Fastapi app factory for forward http proxy.

    Examples:
        The same as [`ForwardHttpProxy.__init__`][fastapi_proxy_lib.core.http.ForwardHttpProxy.__init__].

    Args:
        client: refer to [`ForwardHttpProxy`][fastapi_proxy_lib.core.http.ForwardHttpProxy].
        follow_redirects: refer to [`ForwardHttpProxy`][fastapi_proxy_lib.core.http.ForwardHttpProxy].
        proxy_filter: refer to [`ForwardHttpProxy`][fastapi_proxy_lib.core.http.ForwardHttpProxy].
    """
    forward_http_proxy = ForwardHttpProxy(
        client, proxy_filter=proxy_filter, follow_redirects=follow_redirects
    )

    return _proxy2app(forward_http_proxy)


def reverse_http_app(
    client: Optional[httpx.AsyncClient] = None,
    *,
    base_url: Union[httpx.URL, str],
    follow_redirects: bool = False,
) -> FastAPI:
    """Fastapi app factory for reverse http proxy.

    Examples:
        The same as [`ReverseHttpProxy.__init__`][fastapi_proxy_lib.core.http.ReverseHttpProxy.__init__].

    Args:
        client: refer to [`ReverseHttpProxy`][fastapi_proxy_lib.core.http.ReverseHttpProxy].
        base_url: refer to [`ReverseHttpProxy`][fastapi_proxy_lib.core.http.ReverseHttpProxy].
        follow_redirects: refer to [`ReverseHttpProxy`][fastapi_proxy_lib.core.http.ReverseHttpProxy].
    """
    reverse_http_proxy = ReverseHttpProxy(
        client,
        base_url=base_url,
        follow_redirects=follow_redirects,
    )

    return _proxy2app(reverse_http_proxy)


def reverse_ws_app(
    client: Optional[httpx.AsyncClient] = None,
    *,
    base_url: Union[httpx.URL, str],
    follow_redirects: bool = False,
    max_message_size_bytes: int = DEFAULT_MAX_MESSAGE_SIZE_BYTES,
    queue_size: int = DEFAULT_QUEUE_SIZE,
    keepalive_ping_interval_seconds: Union[
        float, None
    ] = DEFAULT_KEEPALIVE_PING_INTERVAL_SECONDS,
    keepalive_ping_timeout_seconds: Union[
        float, None
    ] = DEFAULT_KEEPALIVE_PING_TIMEOUT_SECONDS,
) -> FastAPI:
    """Fastapi app factory for reverse ws proxy.

    Examples:
        The same as [`ReverseWebSocketProxy.__init__`][fastapi_proxy_lib.core.websocket.ReverseWebSocketProxy.__init__].

    Args:
        client: refer to [`ReverseWebSocketProxy`][fastapi_proxy_lib.core.websocket.ReverseWebSocketProxy].
        base_url: refer to [`ReverseWebSocketProxy`][fastapi_proxy_lib.core.websocket.ReverseWebSocketProxy].
        follow_redirects: refer to [`ReverseWebSocketProxy`][fastapi_proxy_lib.core.websocket.ReverseWebSocketProxy].
        max_message_size_bytes: refer to [`ReverseWebSocketProxy`][fastapi_proxy_lib.core.websocket.ReverseWebSocketProxy].
        queue_size: refer to [`ReverseWebSocketProxy`][fastapi_proxy_lib.core.websocket.ReverseWebSocketProxy].
        keepalive_ping_interval_seconds: refer to [`ReverseWebSocketProxy`][fastapi_proxy_lib.core.websocket.ReverseWebSocketProxy].
        keepalive_ping_timeout_seconds: refer to [`ReverseWebSocketProxy`][fastapi_proxy_lib.core.websocket.ReverseWebSocketProxy].
    """
    reverse_websocket_proxy = ReverseWebSocketProxy(
        client,
        base_url=base_url,
        follow_redirects=follow_redirects,
        max_message_size_bytes=max_message_size_bytes,
        queue_size=queue_size,
        keepalive_ping_interval_seconds=keepalive_ping_interval_seconds,
        keepalive_ping_timeout_seconds=keepalive_ping_timeout_seconds,
    )

    return _proxy2app(reverse_websocket_proxy)
