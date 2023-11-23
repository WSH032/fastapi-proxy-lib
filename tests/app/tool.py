# noqa: D100

import asyncio
import socket
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Type, TypedDict, TypeVar, Union

import httpx
import uvicorn
from fastapi import FastAPI
from starlette.requests import Request
from starlette.websockets import WebSocket
from typing_extensions import Self, override

_Decoratable_T = TypeVar("_Decoratable_T", bound=Union[Callable[..., Any], Type[Any]])

ServerRecvRequestsTypes = Union[Request, WebSocket]


class RequestDict(TypedDict):
    """Request TypedDict."""

    request: Union[ServerRecvRequestsTypes, None]
    """The latest original http/websocket request from the client."""


@dataclass
class AppDataclass4Test:
    """Test app dataclass.

    Attributes:
        app: The FastAPI app for test.
        request_dict: use `request["request"]` to get the latest original http/websocket request from the client.
    """

    app: FastAPI
    request_dict: RequestDict

    def get_request(self) -> ServerRecvRequestsTypes:
        """Get the latest original http/websocket request from the client.

        equal to self.request_dict["request"].
        """
        server_recv_request = self.request_dict["request"]
        assert server_recv_request is not None, "Please send request first."
        return server_recv_request


def _no_override_uvicorn_server(_method: _Decoratable_T) -> _Decoratable_T:
    """Check if the method is already in `uvicorn.Server`."""
    assert not hasattr(
        uvicorn.Server, _method.__name__
    ), f"Override method of `uvicorn.Server` cls : {_method.__name__}"
    return _method


class AeixtTimeoutUndefine:
    """Didn't set `contx_exit_timeout` in `aexit()`."""


aexit_timeout_undefine = AeixtTimeoutUndefine()


# HACK: 不能继承 AbstractAsyncContextManager[Self]
# 目前有问题，继承 AbstractAsyncContextManager 的话pyright也推测不出来类型
# 只能依靠 __aenter__ 和 __aexit__ 的类型注解
class UvicornServer(uvicorn.Server):
    """subclass of `uvicorn.Server` which can use AsyncContext to launch and shutdown automatically.

    Attributes:
        contx_server_task: The task of server.
        contx_socket: The socket of server.

        other attributes are same as `uvicorn.Server`:
            - config: The config arg that be passed in.
            ...
    """

    _contx_server_task: Union["asyncio.Task[None]", None]
    assert not hasattr(uvicorn.Server, "_contx_server_task")

    _contx_socket: Union[socket.socket, None]
    assert not hasattr(uvicorn.Server, "_contx_socket")

    _contx_server_started_event: Union[asyncio.Event, None]
    assert not hasattr(uvicorn.Server, "_contx_server_started_event")

    contx_exit_timeout: Union[int, float, None]
    assert not hasattr(uvicorn.Server, "contx_exit_timeout")

    @override
    def __init__(
        self, config: uvicorn.Config, contx_exit_timeout: Union[int, float, None] = None
    ) -> None:
        """The same as `uvicorn.Server.__init__`."""
        super().__init__(config=config)
        self._contx_server_task = None
        self._contx_socket = None
        self._contx_server_started_event = None
        self.contx_exit_timeout = contx_exit_timeout

    @override
    async def startup(self, sockets: Optional[List[socket.socket]] = None) -> None:
        """The same as `uvicorn.Server.startup`."""
        super_return = await super().startup(sockets=sockets)
        self.contx_server_started_event.set()
        return super_return

    @_no_override_uvicorn_server
    async def aenter(self) -> Self:
        """Launch the server."""
        # 在分配资源之前，先检查是否重入
        if self.contx_server_started_event.is_set():
            raise RuntimeError("DO not launch server by __aenter__ again!")

        # FIXME: # 这个socket被设计为可被同一进程内的多个server共享，可能会引起潜在问题
        self._contx_socket = self.config.bind_socket()

        self._contx_server_task = asyncio.create_task(
            self.serve([self._contx_socket]), name=f"Uvicorn Server Task of {self}"
        )
        # 在 uvicorn.Server 的实现中，Server.serve() 内部会调用 Server.startup() 完成启动
        # 被覆盖的 self.startup() 会在完成时调用 self.contx_server_started_event.set()
        await self.contx_server_started_event.wait()  # 等待服务器确实启动后才返回
        return self

    @_no_override_uvicorn_server
    async def __aenter__(self) -> Self:
        """Launch the server.

        The same as `self.aenter()`.
        """
        return await self.aenter()

    @_no_override_uvicorn_server
    async def aexit(
        self,
        contx_exit_timeout: Union[
            int, float, None, AeixtTimeoutUndefine
        ] = aexit_timeout_undefine,
    ) -> None:
        """Shutdown the server."""
        contx_server_task = self.contx_server_task
        contx_socket = self.contx_socket

        if isinstance(contx_exit_timeout, AeixtTimeoutUndefine):
            contx_exit_timeout = self.contx_exit_timeout

        # 在 uvicorn.Server 的实现中，设置 should_exit 可以使得 server 任务结束
        assert hasattr(self, "should_exit")
        self.should_exit = True

        try:
            await asyncio.wait_for(contx_server_task, timeout=contx_exit_timeout)
        except asyncio.TimeoutError:
            print(f"{contx_server_task.get_name()} timeout!")
        finally:
            # 其实uvicorn.Server会自动关闭socket，这里是为了保险起见
            contx_socket.close()

    @_no_override_uvicorn_server
    async def __aexit__(self, *_: Any, **__: Any) -> None:
        """Shutdown the server.

        The same as `self.aexit()`.
        """
        return await self.aexit()

    @property
    @_no_override_uvicorn_server
    def contx_server_started_event(self) -> asyncio.Event:
        """The event that indicates the server has started.

        When first call the property, it will instantiate a `asyncio.Event()`to
        `self._contx_server_started_event`.

        Warn: This is a internal implementation detail, do not change the event manually.
            - please call the property in `self.aenter()` or `self.startup()` **first**.
            - **Never** call it outside of an async event loop first:
                https://stackoverflow.com/questions/53724665/using-queues-results-in-asyncio-exception-got-future-future-pending-attached
        """
        if self._contx_server_started_event is None:
            self._contx_server_started_event = asyncio.Event()

        return self._contx_server_started_event

    @property
    @_no_override_uvicorn_server
    def contx_socket(self) -> socket.socket:
        """The socket of server.

        Note: must call `self.__aenter__()` first.
        """
        if self._contx_socket is None:
            raise RuntimeError("Please call `self.__aenter__()` first.")
        else:
            return self._contx_socket

    @property
    @_no_override_uvicorn_server
    def contx_server_task(self) -> "asyncio.Task[None]":
        """The task of server.

        Note: must call `self.__aenter__()` first.
        """
        if self._contx_server_task is None:
            raise RuntimeError("Please call `self.__aenter__()` first.")
        else:
            return self._contx_server_task

    @property
    @_no_override_uvicorn_server
    def contx_socket_getname(self) -> Any:
        """Utils for calling self.contx_socket.getsockname().

        Return:
            refer to: https://docs.python.org/zh-cn/3/library/socket.html#socket-families
        """
        return self.contx_socket.getsockname()

    @property
    @_no_override_uvicorn_server
    def contx_socket_url(self) -> httpx.URL:
        """If server is tcp socket, return the url of server.

        Note: The path of url is explicitly set to "/".
        """
        config = self.config
        if config.fd is not None or config.uds is not None:
            raise RuntimeError("Only support tcp socket.")
        host, port = self.contx_socket_getname[:2]
        return httpx.URL(
            host=host,
            port=port,
            scheme="https" if config.is_ssl else "http",
            path="/",
        )
