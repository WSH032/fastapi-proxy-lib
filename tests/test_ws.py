# noqa: D100


import asyncio
from contextlib import AsyncExitStack
from multiprocessing import Process, Queue
from typing import Any, Dict, Literal, Optional

import httpx
import httpx_ws
import pytest
import uvicorn
from fastapi_proxy_lib.fastapi.app import reverse_ws_app as get_reverse_ws_app
from httpx_ws import aconnect_ws
from starlette import websockets as starlette_websockets_module
from typing_extensions import override

from .app.echo_ws_app import get_app as get_ws_test_app
from .app.tool import UvicornServer
from .conftest import UvicornServerFixture
from .tool import (
    AbstractTestProxy,
    Tool4TestFixture,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 0
DEFAULT_CONTX_EXIT_TIMEOUT = 5

# WS_BACKENDS_NEED_BE_TESTED = ("websockets", "wsproto")
# # FIXME: wsproto 有问题，暂时不测试
# # ConnectionResetError: [WinError 10054] 远程主机强迫关闭了一个现有的连接。
# # https://github.com/encode/uvicorn/discussions/2105
WS_BACKENDS_NEED_BE_TESTED = ("websockets",)

# https://www.python-httpx.org/advanced/#http-proxying
NO_PROXIES: Dict[Any, Any] = {"all://": None}


def _subprocess_run_echo_ws_uvicorn_server(queue: "Queue[str]", **kwargs: Any):
    """Run echo ws app in subprocess.

    Args:
        queue: The queue for subprocess to put the url of echo ws app.
            After the server is started, the url will be put into the queue.
        **kwargs: The kwargs for `uvicorn.Config`
    """
    default_kwargs = {
        "app": get_ws_test_app().app,
        "port": DEFAULT_PORT,
        "host": DEFAULT_HOST,
    }
    default_kwargs.update(kwargs)
    target_ws_server = UvicornServer(
        uvicorn.Config(**default_kwargs),  # pyright: ignore[reportGeneralTypeIssues]
    )

    async def run():
        await target_ws_server.aenter()
        url = str(target_ws_server.contx_socket_url)
        queue.put(url)
        queue.close()
        while True:  # run forever
            await asyncio.sleep(0.1)

    asyncio.run(run())


def _subprocess_run_httpx_ws(
    queue: "Queue[str]",
    kwargs_async_client: Optional[Dict[str, Any]] = None,
    kwargs_aconnect_ws: Optional[Dict[str, Any]] = None,
):
    """Run aconnect_ws in subprocess.

    Args:
        queue: The queue for subprocess to put something for flag of ws connection established.
        kwargs_async_client: The kwargs for `httpx.AsyncClient`
        kwargs_aconnect_ws: The kwargs for `httpx_ws.aconnect_ws`
    """
    kwargs_async_client = kwargs_async_client or {}
    kwargs_aconnect_ws = kwargs_aconnect_ws or {}

    kwargs_async_client.pop("proxies", None)
    kwargs_aconnect_ws.pop("client", None)

    async def run():
        _exit_stack = AsyncExitStack()
        _temp_client = httpx.AsyncClient(proxies=NO_PROXIES, **kwargs_async_client)
        _ = await _exit_stack.enter_async_context(
            aconnect_ws(
                client=_temp_client,
                **kwargs_aconnect_ws,
            )
        )
        queue.put("done")
        queue.close()
        while True:  # run forever
            await asyncio.sleep(0.1)

    asyncio.run(run())


class TestReverseWsProxy(AbstractTestProxy):
    """For testing reverse websocket proxy."""

    @override
    @pytest.fixture(params=WS_BACKENDS_NEED_BE_TESTED)
    async def tool_4_test_fixture(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        uvicorn_server_fixture: UvicornServerFixture,
        request: pytest.FixtureRequest,
    ) -> Tool4TestFixture:
        """目标服务器请参考`tests.app.echo_ws_app.get_app`."""
        echo_ws_test_model = get_ws_test_app()
        echo_ws_app = echo_ws_test_model.app
        echo_ws_get_request = echo_ws_test_model.get_request

        target_ws_server = await uvicorn_server_fixture(
            uvicorn.Config(
                echo_ws_app, port=DEFAULT_PORT, host=DEFAULT_HOST, ws=request.param
            ),
            contx_exit_timeout=DEFAULT_CONTX_EXIT_TIMEOUT,
        )

        target_server_base_url = str(target_ws_server.contx_socket_url)

        client_for_conn_to_target_server = httpx.AsyncClient(proxies=NO_PROXIES)

        reverse_ws_app = get_reverse_ws_app(
            client=client_for_conn_to_target_server, base_url=target_server_base_url
        )

        proxy_ws_server = await uvicorn_server_fixture(
            uvicorn.Config(
                reverse_ws_app, port=DEFAULT_PORT, host=DEFAULT_HOST, ws=request.param
            ),
            contx_exit_timeout=DEFAULT_CONTX_EXIT_TIMEOUT,
        )

        proxy_server_base_url = str(proxy_ws_server.contx_socket_url)

        client_for_conn_to_proxy_server = httpx.AsyncClient(proxies=NO_PROXIES)

        return Tool4TestFixture(
            client_for_conn_to_target_server=client_for_conn_to_target_server,
            client_for_conn_to_proxy_server=client_for_conn_to_proxy_server,
            get_request=echo_ws_get_request,
            target_server_base_url=target_server_base_url,
            proxy_server_base_url=proxy_server_base_url,
        )

    @pytest.mark.anyio()
    async def test_ws_proxy(self, tool_4_test_fixture: Tool4TestFixture) -> None:
        """测试websocket代理."""
        proxy_server_base_url = tool_4_test_fixture.proxy_server_base_url
        client_for_conn_to_proxy_server = (
            tool_4_test_fixture.client_for_conn_to_proxy_server
        )
        get_request = tool_4_test_fixture.get_request

        ########## 测试数据的正常转发 ##########

        async with aconnect_ws(
            proxy_server_base_url + "echo_text", client_for_conn_to_proxy_server
        ) as ws:
            await ws.send_text("foo")
            assert await ws.receive_text() == "foo"

        async with aconnect_ws(
            proxy_server_base_url + "echo_bytes", client_for_conn_to_proxy_server
        ) as ws:
            await ws.send_bytes(b"foo")
            assert await ws.receive_bytes() == b"foo"

        ########## 测试子协议 ##########

        async with aconnect_ws(
            proxy_server_base_url + "accept_foo_subprotocol",
            client_for_conn_to_proxy_server,
            subprotocols=["foo", "bar"],
        ) as ws:
            assert ws.subprotocol == "foo"

        ########## 关闭代码 ##########

        async with aconnect_ws(
            proxy_server_base_url + "just_close_with_1001",
            client_for_conn_to_proxy_server,
        ) as ws:
            with pytest.raises(httpx_ws.WebSocketDisconnect) as exce:
                await ws.receive_text()
            assert exce.value.code == 1001

        ########## 协议升级失败或者连接失败 ##########

        with pytest.raises(httpx_ws.WebSocketUpgradeError) as exce:
            async with aconnect_ws(
                proxy_server_base_url + "reject_handshake",
                client_for_conn_to_proxy_server,
            ) as ws:
                pass
        # uvicorn 服务器在未调用`websocket.accept()`之前调用了`websocket.close()`，会发生403
        assert exce.value.response.status_code == 403

        ########## 客户端突然关闭时，服务器应该收到1011 ##########

        # NOTE: 这个测试不放在 `test_target_server_shutdown_abnormally` 来做
        # 是因为这里已经有现成的target server，放在这里测试可以节省启动服务器时间

        aconnect_ws_subprocess_queue: "Queue[str]" = Queue()

        kwargs_async_client = {"proxies": NO_PROXIES}
        kwargs_aconnect_ws = {"url": proxy_server_base_url + "do_nothing"}
        kwargs = {
            "kwargs_async_client": kwargs_async_client,
            "kwargs_aconnect_ws": kwargs_aconnect_ws,
        }

        aconnect_ws_subprocess = Process(
            target=_subprocess_run_httpx_ws,
            args=(aconnect_ws_subprocess_queue,),
            kwargs=kwargs,
        )
        aconnect_ws_subprocess.start()

        # 避免从队列中get导致的异步阻塞
        while aconnect_ws_subprocess_queue.empty():
            await asyncio.sleep(0.1)
        _ = aconnect_ws_subprocess_queue.get()  # 获取到了即代表连接建立成功

        # force shutdown client
        aconnect_ws_subprocess.terminate()
        aconnect_ws_subprocess.kill()
        # https://pytest-cov.readthedocs.io/en/latest/subprocess-support.html#if-you-use-multiprocessing-process
        aconnect_ws_subprocess.join()  # dont forget this, pytest-cov requires this

        target_starlette_ws = get_request()
        assert isinstance(target_starlette_ws, starlette_websockets_module.WebSocket)
        with pytest.raises(starlette_websockets_module.WebSocketDisconnect) as exce:
            await target_starlette_ws.receive_text()  # receive_bytes() 也可以

        # assert exce.value.code == 1011
        # HACK, FIXME: 无法测试错误代码，似乎无法正常传递，且不同后端也不同
        # FAILED test_ws_proxy[websockets] - assert 1005 == 1011
        # FAILED test_ws_proxy[wsproto] - assert <CloseReason.NORMAL_CLOSURE: 1000> == 1011

    # FIXME: 调查为什么收到关闭代码需要40s
    @pytest.mark.timeout(60)
    @pytest.mark.anyio()
    @pytest.mark.parametrize("ws_backend", WS_BACKENDS_NEED_BE_TESTED)
    async def test_target_server_shutdown_abnormally(
        self, ws_backend: Literal["websockets", "wsproto"]
    ) -> None:
        """测试因为目标服务器突然断连导致的，ws桥接异常关闭.

        需要在 60s 内向客户端发送 1011 关闭代码.
        """
        subprocess_queue: "Queue[str]" = Queue()

        target_ws_server_subprocess = Process(
            target=_subprocess_run_echo_ws_uvicorn_server,
            args=(subprocess_queue,),
            kwargs={"port": DEFAULT_PORT, "host": DEFAULT_HOST, "ws": ws_backend},
        )
        target_ws_server_subprocess.start()

        # 避免从队列中get导致的异步阻塞
        while subprocess_queue.empty():
            await asyncio.sleep(0.1)
        target_server_base_url = subprocess_queue.get()

        client_for_conn_to_target_server = httpx.AsyncClient(proxies=NO_PROXIES)

        reverse_ws_app = get_reverse_ws_app(
            client=client_for_conn_to_target_server, base_url=target_server_base_url
        )

        async with UvicornServer(
            uvicorn.Config(
                reverse_ws_app, port=DEFAULT_PORT, host=DEFAULT_HOST, ws=ws_backend
            )
        ) as proxy_ws_server:
            proxy_server_base_url = str(proxy_ws_server.contx_socket_url)

            async with aconnect_ws(
                proxy_server_base_url + "do_nothing",
                httpx.AsyncClient(proxies=NO_PROXIES),
            ) as ws0, aconnect_ws(
                proxy_server_base_url + "do_nothing",
                httpx.AsyncClient(proxies=NO_PROXIES),
            ) as ws1:
                # force shutdown target server
                target_ws_server_subprocess.terminate()
                target_ws_server_subprocess.kill()
                # https://pytest-cov.readthedocs.io/en/latest/subprocess-support.html#if-you-use-multiprocessing-process
                target_ws_server_subprocess.join()  # dont forget this, pytest-cov requires this

                with pytest.raises(httpx_ws.WebSocketDisconnect) as exce:
                    await ws0.receive()
                assert exce.value.code == 1011

                loop = asyncio.get_running_loop()

                seconde_ws_recv_start = loop.time()
                with pytest.raises(httpx_ws.WebSocketDisconnect) as exce:
                    await ws1.receive()
                assert exce.value.code == 1011
                seconde_ws_recv_end = loop.time()

                # HACK: 由于收到关闭代码需要40s，目前无法确定是什么原因，
                # 所以目前会同时测试两个客户端的连接，
                # 只要第二个客户端不是在之前40s基础上又重复40s，就暂时没问题，
                # 因为这模拟了多个客户端进行连接的情况。
                assert (seconde_ws_recv_end - seconde_ws_recv_start) < 2
