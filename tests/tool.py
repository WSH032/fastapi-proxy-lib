# noqa: D100

import abc
from dataclasses import dataclass
from typing import Callable

import httpx
import pytest

from .app.tool import ServerRecvRequestsTypes

WRONG_PROTO_URL = "wrong://wrong.fastapi_proxy_test.wrong/"
WRONG_ASCII_URL = "http://www.\n.com/"
DEFAULT_WRONG_URL = "http://wrong.fastapi_proxy_test.wrong/"
PRIVATE_IP_URL = "http://127.0.0.1/"
DEFAULT_URL = "http://www.example.com/"


@dataclass
class Tool4TestFixture:
    """Tool for test server.

    Attributes:
        client_for_conn_to_target_server: The client for connecting to target server.
        client_for_conn_to_proxy_server: The client for connecting to proxy server.
        get_request: Get the latest original http/websocket request from the client.
        target_server_base_url: The base url of target server.
        proxy_server_base_url: The base url of proxy server.
    """

    client_for_conn_to_target_server: httpx.AsyncClient
    client_for_conn_to_proxy_server: httpx.AsyncClient
    get_request: Callable[[], ServerRecvRequestsTypes]
    target_server_base_url: str
    proxy_server_base_url: str


class AbstractTestProxy(abc.ABC):
    """Abstract class for testing proxy."""

    @abc.abstractmethod
    def tool_4_test_fixture(self) -> Tool4TestFixture:
        """Get the tool for test server."""


def check_if_err_resp_is_from_px_serv(resp: httpx.Response) -> None:
    """Check if the response about error info is actively sent by proxy server.

    If not, will raise AssertionError
    """
    assert resp.is_error, f"Not a error response: {resp}"
    try:
        resp_body = resp.json()
    except Exception:
        pytest.fail(f"Not from proxy server: {resp}")
    # 这两条消息是代理服务器主动返回的错误信息的API的一部分
    assert "err_type" in resp_body["detail"]
    assert "msg" in resp_body["detail"]
