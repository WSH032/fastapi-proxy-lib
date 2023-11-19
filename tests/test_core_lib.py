# noqa: D100

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi_proxy_lib.core._tool import (
    BaseURLError,
    ErrMsg,
    check_base_url,
    default_proxy_filter,
    return_err_msg_response,
)
from fastapi_proxy_lib.core.http import ReverseHttpProxy
from fastapi_proxy_lib.fastapi.app import forward_http_app, reverse_http_app
from fastapi_proxy_lib.fastapi.router import RouterHelper
from starlette.responses import JSONResponse

from .tool import DEFAULT_URL


def test_base_url_cheking_when_init() -> None:
    """测试实例化时不符合输入要求的base_url实参报错."""
    # 不以 `"/"` 结尾
    with pytest.raises(BaseURLError):
        reverse_http_app(base_url="http://www.echo.com/path")
    with pytest.raises(BaseURLError):
        reverse_http_app(base_url="http://www.echo.com")
    # 没有netloc
    with pytest.raises(BaseURLError):
        reverse_http_app(base_url="http://")
    # 没有scheme
    with pytest.raises(BaseURLError):
        reverse_http_app(base_url="www.echo.com")
    # 有query或fragment
    with pytest.warns():
        reverse_http_app(base_url="http://www.echo.com/?q=foo")
    with pytest.warns():
        reverse_http_app(base_url="http://www.echo.com/#foo")

    # 测试是否能正确规范化
    with pytest.warns():
        assert check_base_url("http://www.echo.com/?p=1#foo") == "http://www.echo.com/"


@pytest.mark.anyio()
async def test_func_return_err_msg_response() -> None:
    """Test `fastapi_proxy_lib.core._tool.return_err_msg_response()`."""

    class FooError(Exception):
        pass

    test_error = FooError("bar")
    test_err_msg = ErrMsg(err_type="FooError", msg="bar")

    app = FastAPI()

    @app.get("/exception")
    async def _() -> JSONResponse:
        return return_err_msg_response(test_error, status_code=0)

    @app.get("/mapping")
    async def _() -> JSONResponse:
        return return_err_msg_response(test_err_msg, status_code=0)

    # 测试是否满足以下规范
    # {
    #     "detail": {
    #         "err_type": "RuntimeError",
    #         "msg": "Something wrong."
    #     }
    # }

    client = httpx.AsyncClient(app=app, base_url="http://www.example.com")
    resp = await client.get("http://www.example.com/exception")
    assert resp.status_code == 0
    assert resp.json()["detail"] == test_err_msg
    resp = await client.get("/mapping")
    assert resp.status_code == 0
    assert resp.json()["detail"] == test_err_msg

    # 如果只传入 _msg 或者 _exc_info，但不传入 logger，会有警告
    with pytest.warns():
        return_err_msg_response(test_error, status_code=0, _msg="foo")
    with pytest.warns():
        return_err_msg_response(test_error, status_code=0, _exc_info=test_error)


def test_func_default_proxy_filter() -> None:
    """Test `fastapi_proxy_lib.core._tool.default_proxy_filter()`."""
    # 禁止访问私有IP
    assert default_proxy_filter(httpx.URL("http://www.example.com")) is None
    assert default_proxy_filter(httpx.URL("http://1.1.1.1")) is None
    assert default_proxy_filter(httpx.URL("http://127.0.0.1")) is not None


def test_non_filter_warning_for_forward_proxy() -> None:
    """Forward proxy中未指定 proxy filter 会发出警告."""
    with pytest.warns():
        forward_http_app()


def test_duplicate_router_warning() -> None:
    """重复注册代理在同一个Router中会发出警告."""
    helper = RouterHelper()

    proxy0 = ReverseHttpProxy(base_url=DEFAULT_URL)
    proxy1 = ReverseHttpProxy(base_url=DEFAULT_URL)

    router0 = APIRouter()
    router1 = APIRouter()

    helper.register_router(proxy0, router0)
    # 使用同一个router进行注册会发出警告
    with pytest.warns():
        helper.register_router(proxy1, router0)

    anything_except_router = object()
    with pytest.raises(TypeError):
        helper.register_router(
            anything_except_router,  # pyright: ignore[reportGeneralTypeIssues]
            router1,
        )
