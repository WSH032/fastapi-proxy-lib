"""The websocket proxy lib."""

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import (
    TYPE_CHECKING,
    Any,
    List,
    Literal,
    NamedTuple,
    NoReturn,
    Optional,
    Union,
)

import httpx
import httpx_ws
import starlette.websockets as starlette_ws
from httpx_ws._api import (  # HACK: 注意，这个是私有模块
    DEFAULT_KEEPALIVE_PING_INTERVAL_SECONDS,
    DEFAULT_KEEPALIVE_PING_TIMEOUT_SECONDS,
    DEFAULT_MAX_MESSAGE_SIZE_BYTES,
    DEFAULT_QUEUE_SIZE,
)
from starlette import status as starlette_status
from starlette.datastructures import (
    Headers as StarletteHeaders,
)
from starlette.datastructures import (
    MutableHeaders as StarletteMutableHeaders,
)
from starlette.exceptions import WebSocketException as StarletteWebSocketException
from starlette.responses import Response as StarletteResponse
from starlette.responses import StreamingResponse
from starlette.types import Scope
from typing_extensions import TypeAlias, override
from wsproto.events import BytesMessage as WsprotoBytesMessage
from wsproto.events import TextMessage as WsprotoTextMessage

from ._model import BaseProxyModel
from ._tool import (
    check_base_url,
    check_http_version,
)

__all__ = (
    "BaseWebSocketProxy",
    "ReverseWebSocketProxy",
)

if TYPE_CHECKING:
    # 这些是私有模块，无法确定以后版本是否会改变，为了保证运行时不会出错，我们使用TYPE_CHECKING
    from httpx._types import HeaderTypes, QueryParamTypes


#################### Data Model ####################


_ClentToServerTaskType: TypeAlias = "asyncio.Task[starlette_ws.WebSocketDisconnect]"
_ServerToClientTaskType: TypeAlias = "asyncio.Task[httpx_ws.WebSocketDisconnect]"


class _ClientServerProxyTask(NamedTuple):
    """The task group for passing websocket message between client and target server."""

    client_to_server_task: _ClentToServerTaskType
    server_to_client_task: _ServerToClientTaskType


#################### Constant ####################


# https://asgi.readthedocs.io/en/latest/specs/www.html#websocket-connection-scope
SUPPORTED_WS_HTTP_VERSIONS = ("1.1",)
"""The http versions that we supported now. It depends on `httpx`."""


#################### Error ####################


#################### Tools function ####################


def _change_client_header(
    *, headers: StarletteHeaders, target_url: httpx.URL
) -> StarletteMutableHeaders:
    """Change client request headers for sending to proxy server.

    - Change "host" header to `target_url.netloc.decode("ascii")`.

    Args:
        headers: original client request headers.
        target_url: httpx.URL of target server url.

    Returns:
        New requests headers, the copy of original input headers.
    """
    # https://www.starlette.io/requests/#headers
    # https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Connection#syntax
    new_headers = headers.mutablecopy()

    # 将host字段更新为目标url的host
    # TODO: 如果查看httpx.URL源码，就会发现netloc是被字符串编码成bytes的，能否想个办法直接获取字符串来提高性能?
    new_headers["host"] = target_url.netloc.decode("ascii")

    return new_headers


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
    - Even if Exception is raised, the {WebSocket} would **not** be closed automatically, you should close it manually

    Args:
        websocket: The starlette WebSocket that has been connected.
            "has been connected" measn that you have called "websocket.accept" first.

    Raises:
        starlette.websockets.WebSocketDisconnect: If the WebSocket is disconnected.
            WebSocketDisconnect.code is the close code.
            WebSocketDisconnect.reason is the close reason.
            - **This is normal behavior that you should catch**
        StarletteWebSocketException: If receive a invalid message type which is neither bytes nor str.
            StarletteWebSocketException.code = starlette_status.WS_1008_POLICY_VIOLATION
            StarletteWebSocketException.reason is the close reason.

        RuntimeError: If the WebSocket is not connected. Need to call "accept" first.
            If the {websocket} argument you passed in is correct, this error will never be raised, just for asset.

    Returns:
        bytes | str: The received data.
    """
    # 实现参考:
    # https://github.com/encode/starlette/blob/657e7e7b728e13dc66cc3f77dffd00a42545e171/starlette/websockets.py#L107C1-L115C1
    assert (
        websocket.application_state == starlette_ws.WebSocketState.CONNECTED
    ), """WebSocket is not connected. Need to call "accept" first."""

    message = await websocket.receive()
    # maybe raise WebSocketDisconnect
    websocket._raise_on_disconnect(message)  # pyright: ignore [reportPrivateUsage]

    # https://asgi.readthedocs.io/en/latest/specs/www.html#receive-receive-event
    if message.get("bytes") is not None:
        return message["bytes"]
    elif message.get("text") is not None:
        return message["text"]
    else:
        # 这种情况应该不会发生，因为这是ASGI标准
        raise AssertionError("message should have 'bytes' or 'text' key")
        raise StarletteWebSocketException(
            code=starlette_status.WS_1008_POLICY_VIOLATION,
            reason="Invalid message type received (neither bytes nor text).",
        )


# 为什么使用这个函数而不是直接使用httpx_ws_AsyncWebSocketSession.receive_text()
# 请看: https://github.com/frankie567/httpx-ws/discussions/52
async def _httpx_ws_receive_bytes_or_str(
    websocket: httpx_ws.AsyncWebSocketSession,
) -> Union[str, bytes]:
    """Receive bytes or str from httpx_ws AsyncWebSocketSession .

    - There is already a queue inside to store the received data
    - Even if Exception is raised, the {WebSocket} would **not** be closed automatically, you should close it manually
        - except for httpx_ws.WebSocketNetworkError, which will call 'close' automatically

    Args:
        websocket: The httpx_ws AsyncWebSocketSession that has been connected.

    Raises:
        httpx_ws.WebSocketDisconnect: If the WebSocket is disconnected.
            WebSocketDisconnect.code is the close code.
            WebSocketDisconnect.reason is the close reason.
            - **This is normal behavior that you should catch**
        httpx_ws.WebSocketNetworkError: A network error occurred.

        httpx_ws.WebSocketInvalidTypeReceived: If receive a invalid message type which is neither bytes nor str.
            Usually it will never be raised, just for assert

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
        raise httpx_ws.WebSocketInvalidTypeReceived(event)


async def _httpx_ws_send_bytes_or_str(
    websocket: httpx_ws.AsyncWebSocketSession,
    data: Union[str, bytes],
) -> None:
    """Send bytes or str to WebSocket.

    - Usually, when Exception is raised, the {WebSocket} is already closed.

    Args:
        websocket: The httpx_ws.AsyncWebSocketSession that has been connected.
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

    - Even if Exception is raised, the {WebSocket} would **not** be closed automatically, you should close it manually

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
    *, client_ws: starlette_ws.WebSocket, server_ws: httpx_ws.AsyncWebSocketSession
) -> starlette_ws.WebSocketDisconnect:
    """Receive data from client, then send to target server.

    Args:
        client_ws: The websocket which receive data of client.
        server_ws: The websocket which send data to target server.

    Returns:
        If the client_ws sends a shutdown message normally, will return starlette_ws.WebSocketDisconnect.

    Raises:
        error for receiving: refer to `_starlette_ws_receive_bytes_or_str`
        error for sending: refer to `_httpx_ws_send_bytes_or_str`
    """
    while True:
        try:
            receive = await _starlette_ws_receive_bytes_or_str(client_ws)
        except starlette_ws.WebSocketDisconnect as e:
            return e
        else:
            await _httpx_ws_send_bytes_or_str(server_ws, receive)


async def _wait_server_then_send_to_client(
    *, client_ws: starlette_ws.WebSocket, server_ws: httpx_ws.AsyncWebSocketSession
) -> httpx_ws.WebSocketDisconnect:
    """Receive data from target server, then send to client.

    Args:
        client_ws: The websocket which send data to client.
        server_ws: The websocket which receive data of target server.

    Returns:
        If the server_ws sends a shutdown message normally, will return httpx_ws.WebSocketDisconnect.

    Raises:
        error for receiving: refer to `_httpx_ws_receive_bytes_or_str`
        error for sending: refer to `_starlette_ws_send_bytes_or_str`
    """
    while True:
        try:
            receive = await _httpx_ws_receive_bytes_or_str(server_ws)
        except httpx_ws.WebSocketDisconnect as e:
            return e
        else:
            await _starlette_ws_send_bytes_or_str(client_ws, receive)


async def _close_ws(
    *,
    client_to_server_task: _ClentToServerTaskType,
    server_to_client_task: _ServerToClientTaskType,
    client_ws: starlette_ws.WebSocket,
    server_ws: httpx_ws.AsyncWebSocketSession,
) -> None:
    """Close ws connection and send status code based on task results.

    - If there is an error, or can't get status code from tasks, then always send a 1011 status code
    - Will close ws connection whatever happens.

    Args:
        client_to_server_task: client_to_server_task
        server_to_client_task: server_to_client_task
        client_ws: client_ws
        server_ws: server_ws
    """
    try:
        # NOTE: 先判断 cancelled ，因为被取消的 task.exception() 会引发异常
        client_error = (
            asyncio.CancelledError
            if client_to_server_task.cancelled()
            else client_to_server_task.exception()
        )
        server_error = (
            asyncio.CancelledError
            if server_to_client_task.cancelled()
            else server_to_client_task.exception()
        )

        if client_error is None:
            # clinet端收到正常关闭消息，则关闭server端
            disconnection = client_to_server_task.result()
            await server_ws.close(disconnection.code, disconnection.reason)
            return
        elif server_error is None:
            # server端收到正常关闭消息，则关闭client端
            disconnection = server_to_client_task.result()
            await client_ws.close(disconnection.code, disconnection.reason)
            return
        else:
            # 如果上述情况都没有发生，意味着至少其中一个任务发生了异常，导致了另一个任务被取消
            # NOTE: 我们不在这个分支调用 `ws.close`，而是留到最后的 finally 来关闭
            client_info = client_ws.client
            client_host, client_port = (
                (client_info.host, client_info.port)
                if client_info is not None
                else (None, None)
            )
            # 这里不用dedent是为了更好的性能
            msg = f"""\
An error occurred in the websocket connection for {client_host}:{client_port}.
client_error: {client_error}
server_error: {server_error}\
"""
            logging.warning(msg)

    except Exception as e:  # pragma: no cover # 这个分支是一个保险分支，通常无法执行，所以只进行记录
        logging.error(
            f"{e} when close ws connection. client: {client_to_server_task}, server:{server_to_client_task}"
        )
        raise

    finally:
        # 无论如何，确保关闭两个websocket
        # 状态码参考: https://developer.mozilla.org/zh-CN/docs/Web/API/CloseEvent
        # https://datatracker.ietf.org/doc/html/rfc6455#section-7.4.1
        try:
            await client_ws.close(starlette_status.WS_1011_INTERNAL_ERROR)
        except Exception:
            # 这个分支通常会被触发，因为uvicorn服务器在重复调用close时会引发异常
            pass
        try:
            await server_ws.close(starlette_status.WS_1011_INTERNAL_ERROR)
        except Exception as e:  # pragma: no cover
            # 这个分支是一个保险分支，通常无法执行，所以只进行记录
            # 不会触发的原因是，负责服务端 ws 连接的 httpx_ws 支持重复调用close而不引发错误
            logging.debug("Unexpected error for debug", exc_info=e)


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

        - The http version of request must be in [`SUPPORTED_WS_HTTP_VERSIONS`][fastapi_proxy_lib.core.websocket.SUPPORTED_WS_HTTP_VERSIONS].

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

        client_request_subprotocols: Union[
            List[str], None
        ] = _get_client_request_subprotocols(websocket.scope)

        # httpx.stream()
        # refer to: https://www.python-httpx.org/api/#helper-functions
        client_request_headers: "HeaderTypes" = _change_client_header(
            headers=websocket.headers, target_url=target_url
        )
        client_request_params: "QueryParamTypes" = websocket.query_params

        # TODO: 是否可以不检查http版本?
        check_result = check_http_version(websocket.scope, SUPPORTED_WS_HTTP_VERSIONS)
        if check_result is not None:
            # NOTE: return 之前最好关闭websocket
            await websocket.close()
            return check_result

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
            proxy_ws = await stack.enter_async_context(
                httpx_ws.aconnect_ws(
                    # 这个是httpx_ws类型注解的问题，其实是可以使用httpx.URL的
                    url=target_url,  # pyright: ignore [reportGeneralTypeIssues]
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
        except httpx_ws.WebSocketUpgradeError as e:
            # 这个错误是在 httpx.stream 获取到响应后才返回的, 也就是说至少本服务器的网络应该是正常的
            # 且对于反向ws代理来说，本服务器管理者有义务保证与目标服务器的连接是正常的
            # 所以这里既有可能是客户端的错误，或者是目标服务器拒绝了连接
            # TODO: 也有可能是本服务器的未知错误
            proxy_res = e.response

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

            client_to_server_task = asyncio.create_task(
                _wait_client_then_send_to_server(
                    client_ws=websocket,
                    server_ws=proxy_ws,
                ),
                name="client_to_server_task",
            )
            server_to_client_task = asyncio.create_task(
                _wait_server_then_send_to_client(
                    client_ws=websocket,
                    server_ws=proxy_ws,
                ),
                name="server_to_client_task",
            )
            # 保持强引用: https://docs.python.org/zh-cn/3.12/library/asyncio-task.html#creating-tasks
            task_group = _ClientServerProxyTask(
                client_to_server_task=client_to_server_task,
                server_to_client_task=server_to_client_task,
            )

            # NOTE: 考虑这两种情况：
            # 1. 如果一个任务在发送阶段退出：
            #   这意味着对应发送的ws已经关闭或者出错
            #   那么另一个任务很快就会在接收该ws的时候引发异常而退出
            #   很快，最终两个任务都结束
            #   **这时候pending 可能 为空，而done为两个任务**
            # 2. 如果一个任务在接收阶段退出：
            #   这意味着对应接收的ws已经关闭或者发生出错
            #   - 对于另一个任务的发送，可能会在发送的时候引发异常而退出
            #       - 可能指的是: wsproto后端的uvicorn发送消息永远不会出错
            #       - https://github.com/encode/uvicorn/discussions/2137
            #   - 对于另一个任务的接收，可能会等待很久，才能继续进行发送任务而引发异常而退出
            #   **这时候pending一般为一个未结束任务**
            #
            #   因为第二种情况的存在，所以需要用 wait_for 强制让其退出
            #   但考虑到第一种情况，先等它 1s ，看看能否正常退出
            try:
                _, pending = await asyncio.wait(
                    task_group,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for pending_task in pending:  # NOTE: pending 一般为一个未结束任务，或者为空
                    # 开始取消未结束的任务
                    try:
                        await asyncio.wait_for(pending_task, timeout=1)
                    except asyncio.TimeoutError:
                        logging.debug(f"{pending} TimeoutError, it's normal.")
                    except Exception as e:
                        # 取消期间可能另一个ws会发生异常，这个是正常情况，且会被 asyncio.wait_for 传播
                        logging.debug(
                            f"{pending} raise error when being canceled, it's normal. error: {e}"
                        )
            except Exception as e:  # pragma: no cover # 这个是保险分支，通常无法执行
                logging.warning(
                    f"Something wrong, please contact the developer. error: {e}"
                )
                raise
            finally:
                # 无论如何都要关闭两个websocket
                # NOTE: 这时候两个任务都已经结束
                await _close_ws(
                    client_to_server_task=client_to_server_task,
                    server_to_client_task=server_to_client_task,
                    client_ws=websocket,
                    server_ws=proxy_ws,
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

    @app.websocket_route("/{path:path}")
    async def _(websocket: WebSocket, path: str = ""):
        return await proxy.proxy(websocket=websocket, path=path)

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
        self, *, websocket: starlette_ws.WebSocket, path: Optional[str] = None
    ) -> Union[Literal[False], StarletteResponse]:
        """Establish websocket connection for both client and target_url, then pass messages between them.

        Args:
            websocket: The client websocket requests.
            path: The path params of websocket request, which means the path params of base url.<br>
                If None, will get it from `websocket.path_params`.<br>
                **Usually, you don't need to pass this argument**.

        Returns:
            If the establish websocket connection unsuccessfully:
                - Will call `websocket.close()` to send code `4xx`
                - Then return a `StarletteResponse` from target server
            If the establish websocket connection successfully:
                - Will run forever until the connection is closed. Then return False.
        """
        base_url = self.base_url

        # 只取第一个路径参数。注意，我们允许没有路径参数，这代表直接请求
        path_param: str = (
            path if path is not None else next(iter(websocket.path_params.values()), "")
        )

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
