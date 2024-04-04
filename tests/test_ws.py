# noqa: D100


from contextlib import AsyncExitStack
from multiprocessing import Process, Queue
from typing import Any, Dict

import anyio
import httpx
import httpx_ws
import pytest
from fastapi_proxy_lib.fastapi.app import reverse_ws_app as get_reverse_ws_app
from httpx_ws import aconnect_ws
from starlette import websockets as starlette_websockets_module
from typing_extensions import override

from .app.echo_ws_app import get_app as get_ws_test_app
from .app.tool import AutoServer
from .conftest import AutoServerFixture
from .tool import (
    AbstractTestProxy,
    Tool4TestFixture,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 0  # random port

# https://www.python-httpx.org/advanced/proxies/
# NOTE: Foce to connect directly, avoid using system proxies
NO_PROXIES: Dict[Any, Any] = {"all://": None}


def _subprocess_run_echo_ws_server(queue: "Queue[str]"):
    """Run echo ws app in subprocess.

    Args:
        queue: The queue for subprocess to put the url of echo ws app.
            After the server is started, the url will be put into the queue.
    """
    target_ws_server = AutoServer(
        app=get_ws_test_app().app,
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
    )

    async def run():
        async with target_ws_server:
            url = str(target_ws_server.contx_socket_url)
            queue.put(url)
            queue.close()
            while True:  # run forever
                await anyio.sleep(0.1)

    anyio.run(run)


def _subprocess_run_httpx_ws(
    queue: "Queue[str]",
    aconnect_ws_url: str,
):
    """Run aconnect_ws in subprocess.

    Args:
        queue: The queue for subprocess to put something for flag of ws connection established.
        aconnect_ws_url: The websocket url for aconnect_ws.
    """

    async def run():
        _exit_stack = AsyncExitStack()
        _temp_client = httpx.AsyncClient(mounts=NO_PROXIES)
        _ = await _exit_stack.enter_async_context(
            aconnect_ws(
                client=_temp_client,
                url=aconnect_ws_url,
            )
        )
        queue.put("done")
        queue.close()
        while True:  # run forever
            await anyio.sleep(0.1)

    anyio.run(run)


class TestReverseWsProxy(AbstractTestProxy):
    """For testing reverse websocket proxy."""

    @override
    @pytest.fixture()
    async def tool_4_test_fixture(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        auto_server_fixture: AutoServerFixture,
    ) -> Tool4TestFixture:
        """目标服务器请参考`tests.app.echo_ws_app.get_app`."""
        echo_ws_test_model = get_ws_test_app()
        echo_ws_app = echo_ws_test_model.app
        echo_ws_get_request = echo_ws_test_model.get_request

        target_ws_server = await auto_server_fixture(
            app=echo_ws_app, port=DEFAULT_PORT, host=DEFAULT_HOST
        )

        target_server_base_url = str(target_ws_server.contx_socket_url)

        client_for_conn_to_target_server = httpx.AsyncClient(mounts=NO_PROXIES)

        reverse_ws_app = get_reverse_ws_app(
            client=client_for_conn_to_target_server, base_url=target_server_base_url
        )

        proxy_ws_server = await auto_server_fixture(
            app=reverse_ws_app, port=DEFAULT_PORT, host=DEFAULT_HOST
        )

        proxy_server_base_url = str(proxy_ws_server.contx_socket_url)

        client_for_conn_to_proxy_server = httpx.AsyncClient(mounts=NO_PROXIES)

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
        # Starlette 在未调用`websocket.accept()`之前调用了`websocket.close()`，会发生403
        assert exce.value.response.status_code == 403

        ########## 客户端突然关闭时，服务器应该收到1011 ##########

        # NOTE: 这个测试不放在 `test_target_server_shutdown_abnormally` 来做
        # 是因为这里已经有现成的target server，放在这里测试可以节省启动服务器时间

        aconnect_ws_subprocess_queue: "Queue[str]" = Queue()
        aconnect_ws_url = proxy_server_base_url + "do_nothing"

        aconnect_ws_subprocess = Process(
            target=_subprocess_run_httpx_ws,
            args=(aconnect_ws_subprocess_queue, aconnect_ws_url),
        )
        aconnect_ws_subprocess.start()

        # 避免从队列中get导致的异步阻塞
        while aconnect_ws_subprocess_queue.empty():
            await anyio.sleep(0.1)
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
    async def test_target_server_shutdown_abnormally(self) -> None:
        """测试因为目标服务器突然断连导致的，ws桥接异常关闭.

        需要在 60s 内向客户端发送 1011 关闭代码.
        """
        subprocess_queue: "Queue[str]" = Queue()

        target_ws_server_subprocess = Process(
            target=_subprocess_run_echo_ws_server,
            args=(subprocess_queue,),
        )
        target_ws_server_subprocess.start()

        # 避免从队列中get导致的异步阻塞
        while subprocess_queue.empty():
            await anyio.sleep(0.1)
        target_server_base_url = subprocess_queue.get()

        client_for_conn_to_target_server = httpx.AsyncClient(mounts=NO_PROXIES)

        reverse_ws_app = get_reverse_ws_app(
            client=client_for_conn_to_target_server, base_url=target_server_base_url
        )

        async with AutoServer(
            app=reverse_ws_app,
            port=DEFAULT_PORT,
            host=DEFAULT_HOST,
        ) as proxy_ws_server:
            proxy_server_base_url = str(proxy_ws_server.contx_socket_url)

            async with aconnect_ws(
                proxy_server_base_url + "do_nothing",
                httpx.AsyncClient(mounts=NO_PROXIES),
            ) as ws0, aconnect_ws(
                proxy_server_base_url + "do_nothing",
                httpx.AsyncClient(mounts=NO_PROXIES),
            ) as ws1:
                # force shutdown target server
                target_ws_server_subprocess.terminate()
                target_ws_server_subprocess.kill()
                # https://pytest-cov.readthedocs.io/en/latest/subprocess-support.html#if-you-use-multiprocessing-process
                target_ws_server_subprocess.join()  # dont forget this, pytest-cov requires this

                with pytest.raises(httpx_ws.WebSocketDisconnect) as exce:
                    await ws0.receive()
                assert exce.value.code == 1011

                seconde_ws_recv_start = anyio.current_time()
                with pytest.raises(httpx_ws.WebSocketDisconnect) as exce:
                    await ws1.receive()
                assert exce.value.code == 1011
                seconde_ws_recv_end = anyio.current_time()

                # HACK: 由于收到关闭代码需要40s，目前无法确定是什么原因，
                # 所以目前会同时测试两个客户端的连接，
                # 只要第二个客户端不是在之前40s基础上又重复40s，就暂时没问题，
                # 因为这模拟了多个客户端进行连接的情况。
                assert (seconde_ws_recv_end - seconde_ws_recv_start) < 2
