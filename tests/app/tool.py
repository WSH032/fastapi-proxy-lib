# noqa: D100

from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Literal, Optional, TypedDict, Union

import anyio
import httpx
import sniffio
import uvicorn
from fastapi import FastAPI
from hypercorn import Config as HyperConfig
from hypercorn.asyncio.run import (
    worker_serve as hyper_aio_worker_serve,  # pyright: ignore[reportUnknownVariableType]
)
from hypercorn.trio.run import (
    worker_serve as hyper_trio_worker_serve,  # pyright: ignore[reportUnknownVariableType]
)
from hypercorn.utils import (
    repr_socket_addr,  # pyright: ignore[reportUnknownVariableType]
)
from hypercorn.utils import (
    wrap_app as hyper_wrap_app,  # pyright: ignore[reportUnknownVariableType]
)
from starlette.requests import Request
from starlette.websockets import WebSocket
from typing_extensions import Self, assert_never

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


class _UvicornServer(uvicorn.Server):
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
        assert not self.should_exit, "The server has already exited."
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

        # Implement ref:
        # https://github.com/encode/uvicorn/blob/a2219eb2ed2bbda4143a0fb18c4b0578881b1ae8/uvicorn/server.py#L201-L220
        host, port = self._socket.getsockname()[:2]
        return httpx.URL(
            host=host,
            port=port,
            scheme="https" if config.is_ssl else "http",
            path="/",
        )


class _HypercornServer:
    """An AsyncContext to launch and shutdown Hypercorn server automatically."""

    def __init__(self, app: FastAPI, config: HyperConfig):
        self.config = config
        self.app = app
        self.should_exit = anyio.Event()

    async def __aenter__(self) -> Self:
        """Launch the server."""
        self._exit_stack = AsyncExitStack()

        self.current_async_lib = sniffio.current_async_library()

        if self.current_async_lib == "asyncio":
            serve_func = (  # pyright: ignore[reportUnknownVariableType]
                hyper_aio_worker_serve
            )

            # Implement ref:
            # https://github.com/pgjones/hypercorn/blob/3fbd5f245e5dfeaba6ad852d9135d6a32b228d05/src/hypercorn/asyncio/run.py#L89-L90
            self._sockets = self.config.create_sockets()

        elif self.current_async_lib == "trio":
            serve_func = (  # pyright: ignore[reportUnknownVariableType]
                hyper_trio_worker_serve
            )

            # Implement ref:
            # https://github.com/pgjones/hypercorn/blob/3fbd5f245e5dfeaba6ad852d9135d6a32b228d05/src/hypercorn/trio/run.py#L51-L56
            self._sockets = self.config.create_sockets()
            for sock in self._sockets.secure_sockets:
                sock.listen(self.config.backlog)
            for sock in self._sockets.insecure_sockets:
                sock.listen(self.config.backlog)

        else:
            raise RuntimeError(f"Unsupported async library {self.current_async_lib!r}")

        async def serve() -> None:
            # Implement ref:
            #   https://github.com/pgjones/hypercorn/blob/3fbd5f245e5dfeaba6ad852d9135d6a32b228d05/src/hypercorn/asyncio/__init__.py#L12-L46
            #   https://github.com/pgjones/hypercorn/blob/3fbd5f245e5dfeaba6ad852d9135d6a32b228d05/src/hypercorn/trio/__init__.py#L14-L52
            await serve_func(
                hyper_wrap_app(
                    self.app,  # pyright: ignore[reportArgumentType]
                    self.config.wsgi_max_body_size,
                    mode=None,
                ),
                self.config,
                shutdown_trigger=self.should_exit.wait,
                sockets=self._sockets,
            )

        task_group = await self._exit_stack.enter_async_context(
            anyio.create_task_group()
        )
        task_group.start_soon(serve, name=f"Hypercorn Server Task of {self}")
        return self

    async def __aexit__(self, *_: Any, **__: Any) -> None:
        """Shutdown the server."""
        assert not self.should_exit.is_set(), "The server has already exited."
        self.should_exit.set()
        await self._exit_stack.__aexit__(*_, **__)

    @property
    def contx_socket_url(self) -> httpx.URL:
        """If server is tcp socket, return the url of server.

        Note: The path of url is explicitly set to "/".
        """
        config = self.config
        sockets = self._sockets

        # Implement ref:
        #   https://github.com/pgjones/hypercorn/blob/3fbd5f245e5dfeaba6ad852d9135d6a32b228d05/src/hypercorn/asyncio/run.py#L112-L149
        #   https://github.com/pgjones/hypercorn/blob/3fbd5f245e5dfeaba6ad852d9135d6a32b228d05/src/hypercorn/trio/run.py#L61-L82

        # We only run on one socket each time,
        # so we raise `RuntimeError` to avoid other unknown errors during testing.
        if sockets.insecure_sockets:
            if len(sockets.insecure_sockets) > 1:
                raise RuntimeError("Hypercorn test: Multiple insecure_sockets found.")
            socket = sockets.insecure_sockets[0]
        elif sockets.secure_sockets:
            if len(sockets.secure_sockets) > 1:
                raise RuntimeError("Hypercorn test: secure_sockets sockets found.")
            socket = sockets.secure_sockets[0]
        else:
            raise RuntimeError("Hypercorn test: No socket found.")

        bind = repr_socket_addr(socket.family, socket.getsockname())
        if bind.startswith(("unix:", "fd://")):
            raise RuntimeError("Only support tcp socket.")

        # Implement ref:
        # https://docs.python.org/zh-cn/3/library/socket.html#socket-families
        host, port = bind.split(":")
        port = int(port)

        return httpx.URL(
            host=host,
            port=port,
            scheme="https" if config.ssl_enabled else "http",
            path="/",
        )


class TestServer:
    """An AsyncContext to launch and shutdown Hypercorn or Uvicorn server automatically."""

    def __init__(
        self,
        app: FastAPI,
        host: str,
        port: int,
        server_type: Optional[Literal["uvicorn", "hypercorn"]] = None,
    ):
        """Only support ipv4 address.

        If use uvicorn, it only support asyncio backend.

        If `host` == 0, then use random port.
        """
        server_type = server_type if server_type is not None else "hypercorn"

        self.app = app
        self.host = host
        self.port = port
        self.server_type = server_type

        if self.server_type == "hypercorn":
            config = HyperConfig()
            config.bind = f"{host}:{port}"

            self.config = config
            self.server = _HypercornServer(app, config)
        elif self.server_type == "uvicorn":
            self.config = uvicorn.Config(app, host=host, port=port)
            self.server = _UvicornServer(self.config)
        else:
            assert_never(self.server_type)

    async def __aenter__(self) -> Self:
        """Launch the server."""
        if (
            self.server_type == "uvicorn"
            and sniffio.current_async_library() != "asyncio"
        ):
            raise RuntimeError("Uvicorn server does not support trio backend.")

        self._exit_stack = AsyncExitStack()
        await self._exit_stack.enter_async_context(self.server)
        return self

    async def __aexit__(self, *_: Any, **__: Any) -> None:
        """Shutdown the server."""
        await self._exit_stack.__aexit__(*_, **__)

    @property
    def contx_socket_url(self) -> httpx.URL:
        """If server is tcp socket, return the url of server.

        Note: The path of url is explicitly set to "/".
        """
        return self.server.contx_socket_url
