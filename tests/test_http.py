# noqa: D100


import httpx
import pytest
from fastapi_proxy_lib.core.tool import default_proxy_filter
from typing_extensions import override

from .conftest import AppFactoryFixture, LifeAppDataclass4Test
from .tool import (
    DEFAULT_URL,
    PRIVATE_IP_URL,
    WRONG_PROTO_URL,
    AbstractTestProxy,
    Tool4TestFixture,
    check_if_err_resp_is_from_px_serv,
)

DEFAULT_TARGET_SERVER_BASE_URL = "http://www.echo.com/"
DEFAULT_PROXY_SERVER_BASE_URL = "http://www.proxy.com/"


class TestReverseHttpProxy(AbstractTestProxy):
    """For testing reverse http proxy."""

    @override
    @pytest.fixture()
    async def tool_4_test_fixture(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        echo_http_test_model: LifeAppDataclass4Test,
        reverse_http_app_fct: AppFactoryFixture,
    ) -> Tool4TestFixture:
        """目标服务器请参考`tests.app.echo_http_app.get_app`."""
        client_for_conn_to_target_server = httpx.AsyncClient(
            app=echo_http_test_model.app, base_url=DEFAULT_TARGET_SERVER_BASE_URL
        )

        reverse_http_app = await reverse_http_app_fct(
            client=client_for_conn_to_target_server,
            base_url=DEFAULT_TARGET_SERVER_BASE_URL,
        )

        client_for_conn_to_proxy_server = httpx.AsyncClient(
            app=reverse_http_app, base_url=DEFAULT_PROXY_SERVER_BASE_URL
        )

        get_request = echo_http_test_model.get_request

        return Tool4TestFixture(
            client_for_conn_to_target_server=client_for_conn_to_target_server,
            client_for_conn_to_proxy_server=client_for_conn_to_proxy_server,
            get_request=get_request,
            target_server_base_url=DEFAULT_TARGET_SERVER_BASE_URL,
            proxy_server_base_url=DEFAULT_PROXY_SERVER_BASE_URL,
        )

    @pytest.mark.anyio()
    async def test_all_request_methods(
        self, tool_4_test_fixture: Tool4TestFixture
    ) -> None:
        """测试是否所有的请求方法都能正常工作."""
        client_for_conn_to_proxy_server = (
            tool_4_test_fixture.client_for_conn_to_proxy_server
        )
        proxy_server_base_url = tool_4_test_fixture.proxy_server_base_url

        resp_lst = (
            await client_for_conn_to_proxy_server.get(proxy_server_base_url),
            await client_for_conn_to_proxy_server.post(proxy_server_base_url),
            await client_for_conn_to_proxy_server.put(proxy_server_base_url),
            await client_for_conn_to_proxy_server.head(proxy_server_base_url),
            await client_for_conn_to_proxy_server.options(proxy_server_base_url),
            await client_for_conn_to_proxy_server.delete(proxy_server_base_url),
            await client_for_conn_to_proxy_server.patch(proxy_server_base_url),
        )
        assert all(resp.is_success for resp in resp_lst)

    @pytest.mark.anyio()
    async def test_if_the_header_is_properly_handled(
        self, tool_4_test_fixture: Tool4TestFixture
    ) -> None:
        """测试是否正确处理请求头."""
        client_for_conn_to_proxy_server = (
            tool_4_test_fixture.client_for_conn_to_proxy_server
        )
        proxy_server_base_url = tool_4_test_fixture.proxy_server_base_url
        target_server_base_url = tool_4_test_fixture.target_server_base_url

        ########## 测试 keep_alive 检查点 ##########

        # 客户端关闭连接请求 和 常规操作:
        #   1.无损转发请求头至目标服务器
        #   2.正确处理 host 请求头

        proxy_resp = await client_for_conn_to_proxy_server.head(
            proxy_server_base_url + "head/return_keep_alive_headers",
            headers={
                "foo": "bar",
                "Connection": "close",
            },
        )

        target_server_recv_request = tool_4_test_fixture.get_request()

        # 测试是否尊重客户端关闭连接请求
        assert "close" in proxy_resp.headers["connection"]

        # 测试是否无损转发请求头至目标服务器
        assert target_server_recv_request.headers["foo"] == "bar"

        # 测试是否代理服务器强制发送"connection: keep-alive"请求头至目标服务器
        assert "keep-alive" in target_server_recv_request.headers["connection"]

        # 测试是否正确处理 host 请求头
        assert target_server_recv_request.headers["host"] == httpx.URL(
            target_server_base_url
        ).netloc.decode("ascii")

        # 客户端保活请求

        proxy_resp = await client_for_conn_to_proxy_server.head(
            proxy_server_base_url + "head/return_keep_alive_headers",
            headers={
                "Connection": "keep-alive",
                "Keep-Alive": "timeout=5, max=1000",
            },
        )
        target_server_recv_request = tool_4_test_fixture.get_request()
        # 测试是否屏蔽了 keep-alive 请求头
        assert "keep-alive" not in target_server_recv_request.headers

        ########## 测试 close_connection 检查点 ##########

        # 测试是否尊重客户端保活连接请求
        proxy_resp = await client_for_conn_to_proxy_server.head(
            proxy_server_base_url + "head/return_close_connection_headers",
            headers={
                "Connection": "keep-alive",
                "Keep-Alive": "timeout=5, max=1000",
            },
        )
        assert (
            "connection" not in proxy_resp.headers
            or "close" not in proxy_resp.headers["connection"]
        )

        # 测试是否尊重客户端关闭连接请求
        proxy_resp = await client_for_conn_to_proxy_server.head(
            proxy_server_base_url + "head/return_close_connection_headers",
            headers={
                "Connection": "close",
            },
        )
        assert "close" in proxy_resp.headers["connection"]

    @pytest.mark.anyio()
    async def test_if_the_proxy_forwarding_is_correct(
        self, tool_4_test_fixture: Tool4TestFixture
    ) -> None:
        """测试代理服务器的转发功能是否正常."""
        client_for_conn_to_proxy_server = (
            tool_4_test_fixture.client_for_conn_to_proxy_server
        )
        proxy_server_base_url = tool_4_test_fixture.proxy_server_base_url

        # 测试目标服务器响应体转发正常
        r = await client_for_conn_to_proxy_server.get(
            proxy_server_base_url + "get/echo_headers_and_params",
            headers={"foo": "bar"},
        )
        assert r.json()["foo"] == "bar"

        # 测试客户端请求体转发正常
        r = await client_for_conn_to_proxy_server.post(
            proxy_server_base_url + "post/echo_body",
            json={"foo": "bar"},
        )
        assert r.json()["foo"] == "bar"

        # 测试目标服务文件转发正常
        file_str = "你好"
        r = await client_for_conn_to_proxy_server.put(
            proxy_server_base_url + f"put/echo_file?content={file_str}",
        )
        assert r.content.decode("utf-8") == file_str

    @pytest.mark.anyio()
    async def test_bad_url_request(
        self,
        reverse_http_app_fct: AppFactoryFixture,
    ) -> None:
        """测试坏URL请求的报错功能."""
        client_for_conn_to_target_server = httpx.AsyncClient()

        reverse_http_app = await reverse_http_app_fct(
            client=client_for_conn_to_target_server,
            base_url=WRONG_PROTO_URL,
        )

        client_for_conn_to_proxy_server = httpx.AsyncClient(
            app=reverse_http_app, base_url=DEFAULT_PROXY_SERVER_BASE_URL
        )

        r = await client_for_conn_to_proxy_server.get(DEFAULT_PROXY_SERVER_BASE_URL)
        assert r.status_code == 502
        check_if_err_resp_is_from_px_serv(r)


class TestForwardHttpProxy(AbstractTestProxy):
    """For testing forward http proxy."""

    @pytest.fixture()
    async def tool_4_test_fixture(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        echo_http_test_model: LifeAppDataclass4Test,
        forward_http_app_fct: AppFactoryFixture,
    ) -> Tool4TestFixture:
        """目标服务器请参考`tests.app.echo_http_app.get_app`."""
        client_for_conn_to_target_server = httpx.AsyncClient(
            app=echo_http_test_model.app, base_url=DEFAULT_TARGET_SERVER_BASE_URL
        )

        forward_http_app = await forward_http_app_fct(
            client=client_for_conn_to_target_server, proxy_filter=default_proxy_filter
        )

        client_for_conn_to_proxy_server = httpx.AsyncClient(
            app=forward_http_app, base_url=DEFAULT_PROXY_SERVER_BASE_URL
        )

        get_request = echo_http_test_model.get_request

        return Tool4TestFixture(
            client_for_conn_to_target_server=client_for_conn_to_target_server,
            client_for_conn_to_proxy_server=client_for_conn_to_proxy_server,
            get_request=get_request,
            target_server_base_url=DEFAULT_TARGET_SERVER_BASE_URL,
            proxy_server_base_url=DEFAULT_PROXY_SERVER_BASE_URL,
        )

    @pytest.mark.anyio()
    async def test_all_request_methods(
        self, tool_4_test_fixture: Tool4TestFixture
    ) -> None:
        """测试是否所有的请求方法都能正常工作."""
        client_for_conn_to_proxy_server = (
            tool_4_test_fixture.client_for_conn_to_proxy_server
        )
        proxy_server_base_url = tool_4_test_fixture.proxy_server_base_url
        target_server_base_url = tool_4_test_fixture.target_server_base_url

        test_url = proxy_server_base_url + target_server_base_url

        resp_lst = (
            await client_for_conn_to_proxy_server.get(test_url),
            await client_for_conn_to_proxy_server.post(test_url),
            await client_for_conn_to_proxy_server.put(test_url),
            await client_for_conn_to_proxy_server.head(test_url),
            await client_for_conn_to_proxy_server.options(test_url),
            await client_for_conn_to_proxy_server.delete(test_url),
            await client_for_conn_to_proxy_server.patch(test_url),
        )
        assert all(resp.is_success for resp in resp_lst)

    @pytest.mark.anyio()
    async def test_bad_url_request(
        self,
        forward_http_app_fct: AppFactoryFixture,
    ) -> None:
        """测试坏URL请求的报错功能."""
        client_for_conn_to_target_server = httpx.AsyncClient()

        forward_http_app = await forward_http_app_fct(
            client=client_for_conn_to_target_server, proxy_filter=default_proxy_filter
        )

        client_for_conn_to_proxy_server = httpx.AsyncClient(
            app=forward_http_app, base_url=DEFAULT_PROXY_SERVER_BASE_URL
        )

        # 错误的无法发出请求的URL
        r = await client_for_conn_to_proxy_server.get(
            DEFAULT_PROXY_SERVER_BASE_URL + WRONG_PROTO_URL
        )
        assert r.status_code == 400
        check_if_err_resp_is_from_px_serv(r)

        # 空URL
        r = await client_for_conn_to_proxy_server.get(DEFAULT_PROXY_SERVER_BASE_URL)
        assert r.status_code == 400
        check_if_err_resp_is_from_px_serv(r)

        # 试图访问私有IP的URL
        r = await client_for_conn_to_proxy_server.get(
            DEFAULT_PROXY_SERVER_BASE_URL + PRIVATE_IP_URL
        )
        assert r.status_code == 403
        check_if_err_resp_is_from_px_serv(r)

    @pytest.mark.anyio()
    async def test_500_proxy_server_internal_error(
        self,
        forward_http_app_fct: AppFactoryFixture,
    ) -> None:
        """测试代理服务网络出现问题时的报错功能."""

        async def connect_error_mock_handler(
            request: httpx.Request,
        ) -> httpx.Response:
            """模拟连接错误."""
            raise httpx.ConnectError(
                "MockTransport Raise httpx.ConnectError", request=request
            )

        client_for_conn_to_target_server = httpx.AsyncClient(
            transport=httpx.MockTransport(handler=connect_error_mock_handler)
        )

        forward_http_app = await forward_http_app_fct(
            client=client_for_conn_to_target_server, proxy_filter=default_proxy_filter
        )

        client_for_conn_to_proxy_server = httpx.AsyncClient(
            app=forward_http_app, base_url=DEFAULT_PROXY_SERVER_BASE_URL
        )

        r = await client_for_conn_to_proxy_server.get(
            DEFAULT_PROXY_SERVER_BASE_URL + DEFAULT_URL
        )
        assert r.status_code == 500
        check_if_err_resp_is_from_px_serv(r)

    @pytest.mark.anyio()
    async def test_denial_http2(
        self,
        forward_http_app_fct: AppFactoryFixture,
    ) -> None:
        """测试拒绝HTTP2请求的功能."""
        # HACK: 暂时放弃这个测试
        # httpx.ASGITransport 硬编码为发送 http/1.1 请求
        # 无法正常测试
        return

        proxy_server_base_url = self.proxy_server_base_url

        client_for_conn_to_target_server = httpx.AsyncClient()

        forward_http_app = await forward_http_app_fct(
            client=client_for_conn_to_target_server, proxy_filter=default_proxy_filter
        )

        client_for_conn_to_proxy_server = httpx.AsyncClient(
            app=forward_http_app,
            base_url=proxy_server_base_url,
            http2=True,
            http1=False,
        )

        # 错误的URL
        r = await client_for_conn_to_proxy_server.get(
            proxy_server_base_url + DEFAULT_URL
        )

        assert r.status_code == 505
        check_if_err_resp_is_from_px_serv(r)
