"""The websocket proxy lib."""

import logging
import warnings
from collections import deque
from contextlib import AsyncExitStack
from textwrap import dedent
from typing import (
    TYPE_CHECKING,
    Any,
    List,
    Literal,
    NoReturn,
    Optional,
    Union,
)

import anyio
import anyio.abc
import httpx
import httpx_ws
import starlette.websockets as starlette_ws
from starlette import status as starlette_status
from starlette.responses import Response as StarletteResponse
from starlette.responses import StreamingResponse
from starlette.types import Scope
from typing_extensions import override
from wsproto.events import BytesMessage as WsprotoBytesMessage
from wsproto.events import TextMessage as WsprotoTextMessage

from ._model import BaseProxyModel
from ._tool import (
    change_necessary_client_header_for_httpx,
    check_base_url,
)

# XXX: because these variables are private, we have to use try-except to avoid errors
try:
    from httpx_ws._api import (
        DEFAULT_KEEPALIVE_PING_INTERVAL_SECONDS,
        DEFAULT_KEEPALIVE_PING_TIMEOUT_SECONDS,
        DEFAULT_MAX_MESSAGE_SIZE_BYTES,
        DEFAULT_QUEUE_SIZE,
    )
except ImportError:  # pragma: no cover
    # ref: https://github.com/frankie567/httpx-ws/blob/b2135792141b71551b022ff0d76542a0263a890c/httpx_ws/_api.py#L31-L34
    DEFAULT_KEEPALIVE_PING_TIMEOUT_SECONDS = (  # pyright: ignore[reportConstantRedefinition]
        20.0
    )
    DEFAULT_KEEPALIVE_PING_INTERVAL_SECONDS = (  # pyright: ignore[reportConstantRedefinition]
        20.0
    )
    DEFAULT_MAX_MESSAGE_SIZE_BYTES = (  # pyright: ignore[reportConstantRedefinition]
        65_536
    )
    DEFAULT_QUEUE_SIZE = 512  # pyright: ignore[reportConstantRedefinition]

    msg = dedent(
        """\
        Can not import the default httpx_ws arguments, please open an issue on:
        https://github.com/WSH032/fastapi-proxy-lib\
        """
    )
    warnings.warn(
        msg,
        RuntimeWarning,
        stacklevel=1,
    )


__all__ = (
    "BaseWebSocketProxy",
    "ReverseWebSocketProxy",
)

if TYPE_CHECKING:
    # 这些是私有模块，无法确定以后版本是否会改变，为了保证运行时不会出错，我们使用TYPE_CHECKING
    from httpx._types import HeaderTypes, QueryParamTypes


#################### Data Model ####################


_WsDisconnectType = Union[
    starlette_ws.WebSocketDisconnect, httpx_ws.WebSocketDisconnect
]

_WsDisconnectErrors = (starlette_ws.WebSocketDisconnect, httpx_ws.WebSocketDisconnect)

#################### Constant ####################


#################### Error ####################


#################### Tools function ####################


_change_client_header = change_necessary_client_header_for_httpx


def _get_client_request_subprotocols(ws_scope: Scope) -> Union[List[str], None]:
    """Get client request subprotocols.

    Args:
        ws_scope: client websocket scope.

    Returns:
        If the `ws_scope` has subprotocols, return the subprotocols `List[str]`.
        Else return `None`.
    """
    # https://asgi.readthedocs.io/en/latest/specs/www.html#websocket-connection-scope
    subprotocols: List[str] = ws_scope.get("subprotocols", [])
    if not subprotocols:  # 即为 []
        return None
    return subprotocols


# TODO: 等待starlette官方的支持
# 为什么使用这个函数而不是直接使用starlette_WebSocket.receive_text()
# 请看: https://github.com/encode/starlette/discussions/2310
async def _starlette_ws_receive_bytes_or_str(
    websocket: starlette_ws.WebSocket,
) -> Union[str, bytes]:
    """Receive bytes or str from starlette WebSocket.

    - There is already a queue inside to store the received data
    - Even if `AssertionError` is raised, the `WebSocket` would **not** be closed automatically,
        you should close it manually,

    Args:
        websocket: The starlette WebSocket that has been connected.
            "has been connected" means that you have called "websocket.accept" first.

    Raises:
        starlette.websockets.WebSocketDisconnect: If the WebSocket is disconnected.
            WebSocketDisconnect.code is the close code.
            WebSocketDisconnect.reason is the close reason.
            - **This is normal behavior that you should catch**
        AssertionError:
            - If receive a invalid message type which is neither bytes nor str.
            - RuntimeError: If the WebSocket is not connected. Need to call "accept" first.
                If the `websocket` argument passed in is correct, this error will never be raised, just for assertion.

    Returns:
        bytes | str: The received data.
    """
    # Implement reference:
    # https://github.com/encode/starlette/blob/657e7e7b728e13dc66cc3f77dffd00a42545e171/starlette/websockets.py#L107C1-L115C1
    assert (
        websocket.application_state == starlette_ws.WebSocketState.CONNECTED
    ), """WebSocket is not connected. Need to call "accept" first."""

    message = await websocket.receive()

    if message["type"] == "websocket.disconnect":
        raise starlette_ws.WebSocketDisconnect(message["code"], message.get("reason"))

    # https://asgi.readthedocs.io/en/latest/specs/www.html#receive-receive-event
    if message.get("bytes") is not None:
        return message["bytes"]
    elif message.get("text") is not None:
        return message["text"]
    else:
        # It should never happen, because of the ASGI spec
        raise AssertionError("message should have 'bytes' or 'text' key")


# 为什么使用这个函数而不是直接使用httpx_ws_AsyncWebSocketSession.receive_text()
# 请看: https://github.com/frankie567/httpx-ws/discussions/52
async def _httpx_ws_receive_bytes_or_str(
    websocket: httpx_ws.AsyncWebSocketSession,
) -> Union[str, bytes]:
    """Receive bytes or str from httpx_ws AsyncWebSocketSession .

    - There is already a queue inside to store the received data
    - Even if `AssertionError` or `httpx_ws.WebSocketNetworkError` is raised, the `WebSocket` would **not** be closed automatically,
        you should close it manually,

    Args:
        websocket: The httpx_ws AsyncWebSocketSession that has been connected.

    Raises:
        httpx_ws.WebSocketDisconnect: If the WebSocket is disconnected.
            WebSocketDisconnect.code is the close code.
            WebSocketDisconnect.reason is the close reason.
            - **This is normal behavior that you should catch**
        httpx_ws.WebSocketNetworkError: A network error occurred.
        AssertionError: If receive a invalid message type which is neither bytes nor str.
            Usually it will never be raised, just for assertion

    Returns:
        bytes | str: The received data.
    """
    # 实现参考:
    # https://github.com/frankie567/httpx-ws/blob/1e1c252c2b678f8cc475e1c1546980a784f19702/httpx_ws/_api.py#L296C1-L334C1
    event = await websocket.receive()  # maybe raise httpx_ws.WebSocketNetworkError
    if isinstance(event, WsprotoTextMessage):
        return event.data
    elif isinstance(event, WsprotoBytesMessage):
        if isinstance(
            event.data, bytes
        ):  # pyright: ignore [reportUnnecessaryIsInstance]
            return event.data
        # FIXME: bytes 的类型注解是有问题的，实际上可能是 bytearray
        # https://github.com/frankie567/httpx-ws/discussions/38
        # http://python-hyper.org/projects/wsproto/en/stable/api.html#wsproto.events.TextMessage
        else:
            # 强制保证是bytes
            # FIXME, HACK, XXX: 注意，这是有性能损耗的，调查bytearray是否可以直接用
            return bytes(event.data)
    else:  # pragma: no cover # 无法测试这个分支，因为无法发送这种消息，正常来说也不会被执行，所以我们这里记录critical
        msg = f"Invalid message type received: {type(event)}"
        logging.critical(msg)
        raise AssertionError(event)


async def _httpx_ws_send_bytes_or_str(
    websocket: httpx_ws.AsyncWebSocketSession,
    data: Union[str, bytes],
) -> None:
    """Send bytes or str to WebSocket.

    - Usually, when Exception is raised, the `WebSocket` is already closed.

    Args:
        websocket: The `httpx_ws.AsyncWebSocketSession` that has been connected.
        data: The data to send.

    Raises:
        httpx_ws.WebSocketNetworkError: A network error occurred.
        wsproto.utilities.LocalProtocolError:
            This is raised when the connection is asked to do something
            that is either incompatible with the state or the websocket standard.
            - Mostly it will be raised when the WebSocket has already been disconnected or closed.
    """
    # HACK: make pyright happy
    # 这里有一个pyright问题，需要先判断str
    # 因为 bytes 历史上暗示了 bytes | bytearray | memoryview
    # https://github.com/microsoft/pyright/issues/6227
    if isinstance(data, str):
        await websocket.send_text(data)
    else:
        await websocket.send_bytes(data)


async def _starlette_ws_send_bytes_or_str(
    websocket: starlette_ws.WebSocket,
    data: Union[str, bytes],
) -> None:
    """Send bytes or str to WebSocket.

    - Even if Exception is raised, the `WebSocket` would **not** be closed automatically, you should close it manually

    Args:
        websocket: The starlette_ws.WebSocket that has been connected.
        data: The data to send.

    Raises:
        When websocket has been disconnected, there may be exceptions raised, or maybe not.
        # https://github.com/encode/uvicorn/discussions/2137
        For Uvicorn backend:
        - `wsproto`: nothing raised.
        - `websockets`: websockets.exceptions.ConnectionClosedError

    """
    # HACK: make pyright happy
    # 这里有一个pyright问题，需要先判断str
    # 因为 bytes 历史上暗示了 bytes | bytearray | memoryview
    # https://github.com/microsoft/pyright/issues/6227
    if isinstance(data, str):
        await websocket.send_text(data)
    else:
        await websocket.send_bytes(data)


async def _wait_client_then_send_to_server(
    client_ws: starlette_ws.WebSocket,
    server_ws: httpx_ws.AsyncWebSocketSession,
    ws_disconnect_deque: "deque[_WsDisconnectType]",
    task_group: anyio.abc.TaskGroup,
) -> None:
    """Receive data from client, then send to target server.

    Args:
        client_ws: The websocket which receive data of client.
        server_ws: The websocket which send data to target server.
        ws_disconnect_deque: A deque to store the `WebSocketDisconnect` exception.
        task_group: The task group which run this task.
            if a `WebSocketDisconnect` is raised, will cancel the task group.

    Returns:
        None: Always run forever, except encounter `WebSocketDisconnect`.

    Raises:
        error for receiving: refer to `_starlette_ws_receive_bytes_or_str`.
        error for sending: refer to `_httpx_ws_send_bytes_or_str`.
    """
    try:
        while True:
            receive = await _starlette_ws_receive_bytes_or_str(client_ws)
            await _httpx_ws_send_bytes_or_str(server_ws, receive)
    except _WsDisconnectErrors as ws_disconnect:
        task_group.cancel_scope.cancel()
        with anyio.CancelScope(shield=True):
            ws_disconnect_deque.append(ws_disconnect)


async def _wait_server_then_send_to_client(
    client_ws: starlette_ws.WebSocket,
    server_ws: httpx_ws.AsyncWebSocketSession,
    ws_disconnect_deque: "deque[_WsDisconnectType]",
    task_group: anyio.abc.TaskGroup,
) -> None:
    """Receive data from target server, then send to client.

    Args:
        client_ws: The websocket which receive data of client.
        server_ws: The websocket which send data to target server.
        ws_disconnect_deque: A deque to store the `WebSocketDisconnect` exception.
        task_group: The task group which run this task.
            if a `WebSocketDisconnect` is raised, will cancel the task group.

    Returns:
        None: Always run forever, except encounter `WebSocketDisconnect`.

    Raises:
        error for receiving: refer to `_httpx_ws_receive_bytes_or_str`.
        error for sending: refer to `_starlette_ws_send_bytes_or_str`.
    """
    try:
        while True:
            receive = await _httpx_ws_receive_bytes_or_str(server_ws)
            await _starlette_ws_send_bytes_or_str(client_ws, receive)
    except _WsDisconnectErrors as ws_disconnect:
        task_group.cancel_scope.cancel()
        with anyio.CancelScope(shield=True):
            ws_disconnect_deque.append(ws_disconnect)


async def _close_ws_abnormally(
    client_ws: starlette_ws.WebSocket,
    server_ws: httpx_ws.AsyncWebSocketSession,
    exc: BaseException,
) -> None:
    """Log the exception and close both websockets with code `1011`.

    Args:
        exc: The exception propagated by task group.
        client_ws: client_ws
        server_ws: server_ws
    """
    client_info = client_ws.client
    client_host, client_port = (
        (client_info.host, client_info.port)
        if client_info is not None
        else (None, None)
    )
    # we don't use `dedent` here for better performance
    msg = f"""\
An error occurred in the websocket proxy connection for {client_host}:{client_port}.
errors: {exc!r}\
"""
    logging.warning(msg)

    # Why we use `1011` code, refer to:
    #   https://developer.mozilla.org/zh-CN/docs/Web/API/CloseEvent
    #   https://datatracker.ietf.org/doc/html/rfc6455#section-7.4.1
    await client_ws.close(starlette_status.WS_1011_INTERNAL_ERROR)
    await server_ws.close(starlette_status.WS_1011_INTERNAL_ERROR)


async def _close_ws_normally(
    client_ws: starlette_ws.WebSocket,
    server_ws: httpx_ws.AsyncWebSocketSession,
    ws_disconnect_deque: "deque[_WsDisconnectType]",
) -> None:
    deque_len = len(ws_disconnect_deque)
    if deque_len == 1:
        ws_disconnect = ws_disconnect_deque[0]
        if isinstance(ws_disconnect, starlette_ws.WebSocketDisconnect):
            await server_ws.close(ws_disconnect.code, ws_disconnect.reason)
        else:
            await client_ws.close(ws_disconnect.code, ws_disconnect.reason)
    elif deque_len == 2:
        # If both client and server are disconnected, we do nothing.
        ws_disc_type = {type(ws_disc) for ws_disc in ws_disconnect_deque}
        assert ws_disc_type == {
            starlette_ws.WebSocketDisconnect,
            httpx_ws.WebSocketDisconnect,
        }
        logging.info(
            f"Both client and server received disconnect. {ws_disconnect_deque!r}"
        )
    else:
        raise AssertionError(
            f"There are too many WebSocketDisconnect in deque! {ws_disconnect_deque!r}"
        )


#################### # ####################


class BaseWebSocketProxy(BaseProxyModel):
    """Websocket proxy base class.

    Attributes:
        client: The [`httpx.AsyncClient`](https://www.python-httpx.org/api/#asyncclient) to establish websocket connection.
        follow_redirects: Whether follow redirects of target server.
        max_message_size_bytes: refer to [httpx_ws.aconnect_ws][]
        queue_size: refer to [httpx_ws.aconnect_ws][]
        keepalive_ping_interval_seconds: refer to [httpx_ws.aconnect_ws][]
        keepalive_ping_timeout_seconds: refer to [httpx_ws.aconnect_ws][]

    Tip:
        [`httpx_ws.aconnect_ws`](https://frankie567.github.io/httpx-ws/reference/httpx_ws/#httpx_ws.aconnect_ws)
    """

    client: httpx.AsyncClient
    follow_redirects: bool
    max_message_size_bytes: int
    queue_size: int
    keepalive_ping_interval_seconds: Union[float, None]
    keepalive_ping_timeout_seconds: Union[float, None]

    @override
    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        *,
        follow_redirects: bool = False,
        max_message_size_bytes: int = DEFAULT_MAX_MESSAGE_SIZE_BYTES,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        keepalive_ping_interval_seconds: Union[
            float, None
        ] = DEFAULT_KEEPALIVE_PING_INTERVAL_SECONDS,
        keepalive_ping_timeout_seconds: Union[
            float, None
        ] = DEFAULT_KEEPALIVE_PING_TIMEOUT_SECONDS,
    ) -> None:
        """Http proxy base class.

        Args:
            client: The `httpx.AsyncClient` to establish websocket connection. Defaults to None.<br>
                If None, will create a new `httpx.AsyncClient`,
                else will use the given `httpx.AsyncClient`.
            follow_redirects: Whether follow redirects of target server. Defaults to False.

            max_message_size_bytes: refer to [httpx_ws.aconnect_ws][]
            queue_size: refer to [httpx_ws.aconnect_ws][]
            keepalive_ping_interval_seconds: refer to [httpx_ws.aconnect_ws][]
            keepalive_ping_timeout_seconds: refer to [httpx_ws.aconnect_ws][]

        Tip:
            [`httpx_ws.aconnect_ws`](https://frankie567.github.io/httpx-ws/reference/httpx_ws/#httpx_ws.aconnect_ws)
        """
        self.max_message_size_bytes = max_message_size_bytes
        self.queue_size = queue_size
        self.keepalive_ping_interval_seconds = keepalive_ping_interval_seconds
        self.keepalive_ping_timeout_seconds = keepalive_ping_timeout_seconds
        super().__init__(client, follow_redirects=follow_redirects)

    @override
    async def send_request_to_target(  # pyright: ignore [reportIncompatibleMethodOverride]
        self,
        *,
        websocket: starlette_ws.WebSocket,
        target_url: httpx.URL,
    ) -> Union[Literal[False], StarletteResponse]:
        """Establish websocket connection for both client and target_url, then pass messages between them.

        Args:
            websocket: The client websocket requests.
            target_url: The url of target websocket server.

        Returns:
            If the establish websocket connection unsuccessfully:
                - Will call `websocket.close()` to send code `4xx`
                - Then return a `StarletteResponse` from target server
            If the establish websocket connection successfully:
                - Will run forever until the connection is closed. Then return False.
        """
        client = self.client
        follow_redirects = self.follow_redirects
        max_message_size_bytes = self.max_message_size_bytes
        queue_size = self.queue_size
        keepalive_ping_interval_seconds = self.keepalive_ping_interval_seconds
        keepalive_ping_timeout_seconds = self.keepalive_ping_timeout_seconds

        client_request_subprotocols: Union[List[str], None] = (
            _get_client_request_subprotocols(websocket.scope)
        )

        # httpx.stream()
        # refer to: https://www.python-httpx.org/api/#helper-functions
        client_request_headers: "HeaderTypes" = _change_client_header(
            headers=websocket.headers, target_url=target_url
        )
        client_request_params: "QueryParamTypes" = websocket.query_params

        # DEBUG: 用于调试的记录
        logging.debug(
            "WS: client:%s ; url:%s ; params:%s ; headers:%s",
            websocket.client,
            target_url,
            client_request_params,
            client_request_headers,
        )

        # https://github.com/frankie567/httpx-ws/discussions/11
        # https://docs.python.org/3.12/library/contextlib.html?highlight=asyncexitstack#catching-exceptions-from-enter-methods
        stack = AsyncExitStack()
        try:
            # FIX: https://github.com/WSH032/fastapi-proxy-lib/security/advisories/GHSA-7vwr-g6pm-9hc8
            # time cost: 396 ns ± 3.39 ns
            # 由于这不是原子性的操作，所以不保证一定阻止cookie泄漏
            # 一定能保证修复的方法是通过`_tool.change_necessary_client_header_for_httpx`强制指定优先级最高的cookie头
            client.cookies.clear()

            proxy_ws = await stack.enter_async_context(
                httpx_ws.aconnect_ws(
                    # XXX: 这个是httpx_ws类型注解的问题，其实是可以使用httpx.URL的
                    url=target_url,  # pyright: ignore [reportArgumentType]
                    client=client,
                    max_message_size_bytes=max_message_size_bytes,
                    queue_size=queue_size,
                    keepalive_ping_interval_seconds=keepalive_ping_interval_seconds,
                    keepalive_ping_timeout_seconds=keepalive_ping_timeout_seconds,
                    subprotocols=client_request_subprotocols,
                    # httpx.stream() params
                    # refer to: https://www.python-httpx.org/api/#helper-functions
                    headers=client_request_headers,
                    params=client_request_params,
                    follow_redirects=follow_redirects,
                )
            )
        except httpx_ws.WebSocketUpgradeError as ws_upgrade_exc:
            # 这个错误是在 httpx.stream 获取到响应后才返回的, 也就是说至少本服务器的网络应该是正常的
            # 且对于反向ws代理来说，本服务器管理者有义务保证与目标服务器的连接是正常的
            # 所以这里既有可能是客户端的错误，或者是目标服务器拒绝了连接
            # TODO: 也有可能是本服务器的未知错误
            proxy_res = ws_upgrade_exc.response

            # NOTE: return 之前最好关闭websocket
            # 不调用websocket.accept就发送关闭请求，uvicorn会自动发送403错误
            await websocket.close()
            # TODO: 连接失败的时候httpx_ws会自己关闭连接，但或许这里显式关闭会更好

            # HACK: 这里的返回的响应其实uvicorn不会处理
            return StreamingResponse(
                content=proxy_res.aiter_raw(),
                status_code=proxy_res.status_code,
                headers=proxy_res.headers,
            )

        # NOTE: 对于反向代理服务器，我们不返回 "任何" "具体的内部" 错误信息给客户端，因为这可能涉及到服务器内部的信息泄露

        # NOTE: 请使用 with 语句来 "保证关闭" AsyncWebSocketSession
        async with stack:
            # TODO: websocket.accept 中还有一个headers参数，但是httpx_ws不支持，考虑发起PR
            # https://github.com/frankie567/httpx-ws/discussions/53

            # FIXME: 调查缺少headers参数是否会引起问题，及是否会影响透明代理的无损转发性
            # https://asgi.readthedocs.io/en/latest/specs/www.html#accept-send-event

            # 这时候如果发生错误，退出时 stack 会自动关闭 httpx_ws 连接，所以这里不需要手动关闭
            await websocket.accept(
                subprotocol=proxy_ws.subprotocol
                # headers=...
            )

            ws_disconnect_deque: "deque[_WsDisconnectType]" = deque(maxlen=2)
            caught_tg_exc = None
            try:
                async with anyio.create_task_group() as tg:
                    tg.start_soon(
                        _wait_client_then_send_to_server,
                        websocket,
                        proxy_ws,
                        ws_disconnect_deque,
                        tg,
                        name="client_to_server_task",
                    )
                    tg.start_soon(
                        _wait_server_then_send_to_client,
                        websocket,
                        proxy_ws,
                        ws_disconnect_deque,
                        tg,
                        name="server_to_client_task",
                    )
            except BaseException as base_exc:
                caught_tg_exc = base_exc
                raise  # NOTE: must raise again
            finally:
                # NOTE: DO NOT use `return` in `finally` block
                with anyio.CancelScope(shield=True):
                    # If there are normal disconnection info,
                    # we try to close the connection normally.
                    if ws_disconnect_deque:
                        await _close_ws_normally(
                            client_ws=websocket,
                            server_ws=proxy_ws,
                            ws_disconnect_deque=ws_disconnect_deque,
                        )
                    else:
                        caught_tg_exc = caught_tg_exc or RuntimeError("Unknown error")
                        await _close_ws_abnormally(
                            client_ws=websocket,
                            server_ws=proxy_ws,
                            exc=caught_tg_exc,
                        )

        return False

    @override
    async def proxy(*_: Any, **__: Any) -> NoReturn:
        """NotImplemented."""
        raise NotImplementedError()


# FIXME: 目前无法正确转发目标服务器的响应，包括握手成功的响应头和握手失败的整个响应
# 其中 握手成功的响应头 需要等待 httpx_ws 的支持: https://github.com/frankie567/httpx-ws/pull/54
# 握手失败的响应目前在uvicorn中无法实现
# FIXME: 意外关闭时候的关闭码无法确定
class ReverseWebSocketProxy(BaseWebSocketProxy):
    '''Reverse http proxy.

    Attributes:
        client: The `httpx.AsyncClient` to establish websocket connection.
        base_url: The target proxy server url.
        follow_redirects: Whether follow redirects of target server.
        max_message_size_bytes: refer to [httpx_ws.aconnect_ws][]
        queue_size: refer to [httpx_ws.aconnect_ws][]
        keepalive_ping_interval_seconds: refer to [httpx_ws.aconnect_ws][]
        keepalive_ping_timeout_seconds: refer to [httpx_ws.aconnect_ws][]

    Tip:
        [`httpx_ws.aconnect_ws`](https://frankie567.github.io/httpx-ws/reference/httpx_ws/#httpx_ws.aconnect_ws)

    Bug: There is a issue for handshake response:
        This WebSocket proxy can correctly forward request headers.
        But currently,
        it is unable to properly forward responses from the target service,
        including successful handshake response headers and
        the entire response in case of a handshake failure.

        **In most cases, you don't need to worry about this.**
        It only affects the HTTP handshake before establishing the WebSocket,
        and regular WebSocket messages will be forwarded correctly.

    # # Examples

    ```python
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

    @app.websocket("/{path:path}")
    async def _(websocket: WebSocket):
        return await proxy.proxy(websocket=websocket)

    # Then run shell: `uvicorn <your.py>:app --host http://127.0.0.1:8000 --port 8000`
    # visit the app: `ws://127.0.0.1:8000/`
    # you can establish websocket connection with `ws://echo.websocket.events`
    ```
    '''

    client: httpx.AsyncClient
    base_url: httpx.URL
    follow_redirects: bool
    max_message_size_bytes: int
    queue_size: int
    keepalive_ping_interval_seconds: Union[float, None]
    keepalive_ping_timeout_seconds: Union[float, None]

    @override
    def __init__(
        self,
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
    ) -> None:
        """Reverse http proxy.

        Note: please make sure `base_url` is available.
            Because when an error occurs,
            we cannot distinguish whether it is a proxy server network error, or it is a error of `base_url`.

        Args:
            base_url: The target proxy server url.
            client: The `httpx.AsyncClient` to establish websocket connection. Defaults to None.<br>
                If None, will create a new `httpx.AsyncClient`,
                else will use the given `httpx.AsyncClient`.
            follow_redirects: Whether follow redirects of target server. Defaults to False.

            max_message_size_bytes: refer to [httpx_ws.aconnect_ws][]
            queue_size: refer to [httpx_ws.aconnect_ws][]
            keepalive_ping_interval_seconds: refer to [httpx_ws.aconnect_ws][]
            keepalive_ping_timeout_seconds: refer to [httpx_ws.aconnect_ws][]

        Tip:
            [`httpx_ws.aconnect_ws`](https://frankie567.github.io/httpx-ws/reference/httpx_ws/#httpx_ws.aconnect_ws)
        """
        self.base_url = check_base_url(base_url)
        super().__init__(
            client,
            follow_redirects=follow_redirects,
            max_message_size_bytes=max_message_size_bytes,
            queue_size=queue_size,
            keepalive_ping_interval_seconds=keepalive_ping_interval_seconds,
            keepalive_ping_timeout_seconds=keepalive_ping_timeout_seconds,
        )

    @override
    async def proxy(  # pyright: ignore [reportIncompatibleMethodOverride]
        self, *, websocket: starlette_ws.WebSocket
    ) -> Union[Literal[False], StarletteResponse]:
        """Establish websocket connection for both client and target_url, then pass messages between them.

        Args:
            websocket: The client websocket requests.

        Returns:
            If the establish websocket connection unsuccessfully:
                - Will call `websocket.close()` to send code `4xx`
                - Then return a `StarletteResponse` from target server
            If the establish websocket connection successfully:
                - Will run forever until the connection is closed. Then return False.
        """
        base_url = self.base_url

        # 只取第一个路径参数。注意，我们允许没有路径参数，这代表直接请求
        path_param: str = next(iter(websocket.path_params.values()), "")

        # 将路径参数拼接到目标url上
        # e.g: "https://www.example.com/p0/" + "p1"
        # NOTE: 这里的 path_param 是不带查询参数的，且允许以 "/" 开头 (最终为/p0//p1)
        target_url = base_url.copy_with(
            path=(base_url.path + path_param)
        )  # 耗时: 18.4 µs ± 262 ns

        # self.send_request_to_target 内部会处理连接失败时，返回错误给客户端，所以这里不处理了
        return await self.send_request_to_target(
            websocket=websocket, target_url=target_url
        )
