# noqa: D100

from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, TypedDict, Union

import anyio
import httpx
import uvicorn
from fastapi import FastAPI
from starlette.requests import Request
from starlette.websockets import WebSocket
from typing_extensions import Self

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


class UvicornServer(uvicorn.Server):
    """subclass of `uvicorn.Server` which can use AsyncContext to launch and shutdown automatically."""

    async def __aenter__(self) -> Self:
        """Launch the server."""
        # FIXME: # 这个socket被设计为可被同一进程内的多个server共享，可能会引起潜在问题
        self._socket = self.config.bind_socket()
        self._exit_stack = AsyncExitStack()

        task_group = await self._exit_stack.enter_async_context(
            anyio.create_task_group()
        )
        task_group.start_soon(
            self.serve, [self._socket], name=f"Uvicorn Server Task of {self}"
        )

        return self

    async def __aexit__(self, *_: Any, **__: Any) -> None:
        """Shutdown the server."""
        # 在 uvicorn.Server 的实现中，设置 should_exit 可以使得 server 任务结束
        assert self.should_exit is False, "The server has already exited."
        self.should_exit = True
        await self._exit_stack.__aexit__(*_, **__)

    @property
    def contx_socket_url(self) -> httpx.URL:
        """If server is tcp socket, return the url of server.

        Note: The path of url is explicitly set to "/".
        """
        config = self.config
        if config.fd is not None or config.uds is not None:
            raise RuntimeError("Only support tcp socket.")
        # refer to: https://docs.python.org/zh-cn/3/library/socket.html#socket-families
        host, port = self._socket.getsockname()[:2]
        return httpx.URL(
            host=host,
            port=port,
            scheme="https" if config.is_ssl else "http",
            path="/",
        )
