"""The http proxy lib."""

import logging
from textwrap import dedent
from typing import (
    Any,
    List,
    NamedTuple,
    NoReturn,
    Optional,
    Union,
)

import httpx
from starlette import status as starlette_status
from starlette.background import BackgroundTasks
from starlette.datastructures import (
    Headers as StarletteHeaders,
)
from starlette.datastructures import (
    MutableHeaders as StarletteMutableHeaders,
)
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse
from starlette.responses import StreamingResponse
from typing_extensions import override

from ._model import BaseProxyModel
from ._tool import (
    ProxyFilterProto,
    _RejectedProxyRequestError,  # pyright: ignore [reportPrivateUsage]  # 允许使用本项目内部的私有成员
    check_base_url,
    check_http_version,
    return_err_msg_response,
    warn_for_none_filter,
)

__all__ = (
    "BaseHttpProxy",
    "ReverseHttpProxy",
    "ForwardHttpProxy",
)

#################### Data Model ####################


class _ConnectionHeaderParseResult(NamedTuple):
    """Parse result of "connection" header.

    Attributes:
        require_close: If "connection" header contain "close" value, this will be True, else False.
        new_headers: New request headers.
            "connection" header does not contain a 'close' value, but must contain 'keep-alive' value,
            and the "keep-alive" header was removed.
    """

    require_close: bool
    new_headers: StarletteMutableHeaders


#################### Error ####################


"""带有 '_' 开头的错误，通常用于返回给客户端，而不是在python内部处理."""  # noqa: RUF001

# TODO: 将这些错误移动到 _tool.py 中


class _BadTargetUrlError(ValueError):
    """Bad target url of forward http proxy."""


class _ReverseProxyServerError(RuntimeError):
    """502 reverse proxy server error error."""


#################### Constant ####################

# https://developer.mozilla.org/docs/Web/HTTP/Methods
_NON_REQUEST_BODY_METHODS = ("GET", "HEAD", "OPTIONS", "TRACE")
"""The http methods that should not contain request body."""

# https://asgi.readthedocs.io/en/latest/specs/www.html#http-connection-scope
SUPPORTED_HTTP_VERSIONS = ("1.0", "1.1")
"""The http versions that we supported now. It depends on `httpx`."""

# https://www.python-httpx.org/exceptions/
_400_ERROR_NEED_TO_BE_CATCHED_IN_FORWARD_PROXY = (
    httpx.InvalidURL,  # 解析url时出错
    httpx.UnsupportedProtocol,  # 不支持的协议，如不是http或https
    httpx.ProtocolError,  # 请求或者相应的格式错误，比如缺少host，或者响应头不符合规范
    # ValueError,  # 近乎万能的错误，可能会掩盖不是网络问题的错误
)
"""These errors need to be caught.
When:
- client.build_request
- client.send
"""
_500_ERROR_NEED_TO_BE_CATCHED_IN_FORWARD_PROXY = (
    httpx.ConnectError,  # 我们无法分辨是服务器网络错误导致无法连接，还是客户端输入的了错误且无法连接的url导致了这个错误
)
"""These errors need to be caught and return 5xx status_code.
When:
- client.build_request
- client.send
"""

_502_ERROR_NEED_TO_BE_CATCHED_IN_REVERSE_PROXY = (
    httpx.TransportError,
    httpx.InvalidURL,
    httpx.StreamError,
)
"""When these errors occur in reverse proxy server, we think it is error of server."""


#################### Tools function ####################


def _change_client_header(
    *, headers: StarletteHeaders, target_url: httpx.URL
) -> _ConnectionHeaderParseResult:
    """Change client request headers for sending to proxy server.

    - Will remove "close" value in "connection" header, and add "keep-alive" value to it.
    - And remove "keep-alive" header.
    - And change "host" header to `target_url.netloc.decode("ascii")`.

    Args:
        headers: original client request headers.
        target_url: httpx.URL of target server url.

    Returns:
        _ConnectionHeaderParseResult:
            require_close: If "connection" header contain "close" value, this will be True, else False.
            new_headers: New requests headers, the **copy** of original input headers.
    """
    # https://www.starlette.io/requests/#headers
    # https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Connection#syntax
    new_headers = headers.mutablecopy()

    # NOTE: http标准中规定，connecttion头字段的值用于指示逐段头，而标头是大小写不敏感的，故认为可以转为小写处理
    client_connection_header = [
        v.strip() for v in new_headers.get("connection", "").lower().split(",")
    ]

    # 判断原始请求头中是否有"close"字段，如果有则将其移除，并记录
    if "close" in client_connection_header:
        whether_require_close = True
        client_connection_header.remove("close")
    else:
        whether_require_close = False
    # 强制添加"keep-alive"字段保持连接
    if "keep-alive" not in client_connection_header:
        client_connection_header.insert(0, "keep-alive")
    # 将新的connection头字段更新到新的请求头中
    # 因为 "keep-alive" 一定存在于 "connection"字段 中，所以这里不需要判断是否为空
    new_headers["connection"] = ",".join(client_connection_header)

    # 移除"keep-alive"字段
    if "keep-alive" in new_headers:
        del new_headers["keep-alive"]

    # 将host字段更新为目标url的host
    # TODO: 如果查看httpx.URL源码，就会发现netloc是被字符串编码成bytes的，能否想个办法直接获取字符串来提高性能?
    new_headers["host"] = target_url.netloc.decode("ascii")

    return _ConnectionHeaderParseResult(whether_require_close, new_headers)


def _change_server_header(
    *, headers: httpx.Headers, require_close: bool
) -> httpx.Headers:
    """Change server response headers for sending to client.

    - If require_close is True, will make sure "connection: close" in headers, else will remove it.
    - And remove "keep-alive" header.

    Args:
        headers: server response headers
        require_close: whether require close connection

    Returns:
        The **oringinal headers**, but **had been changed**.
    """
    server_connection_header: List[str] = [
        v.strip() for v in headers.get("connection", "").lower().split(",")
    ]

    # 移除或添加"connection": "close"头
    if require_close:
        if "close" not in server_connection_header:
            server_connection_header.insert(0, "close")
    else:
        if "close" in server_connection_header:
            server_connection_header.remove("close")
    # 将新的connection头字段更新到新的请求头中，如果为空则移除
    if server_connection_header:
        headers["connection"] = ",".join(server_connection_header)
    else:
        if "connection" in headers:
            del headers["connection"]

    # 移除"keep-alive"字段
    if "keep-alive" in headers:
        del headers["keep-alive"]

    return headers


#################### # ####################


class BaseHttpProxy(BaseProxyModel):
    """Http proxy base class.

    Attributes:
        client: The `httpx.AsyncClient` to send http requests.
        follow_redirects: Whether follow redirects of target server.
    """

    @override
    async def send_request_to_target(  # pyright: ignore [reportIncompatibleMethodOverride]
        self, *, request: StarletteRequest, target_url: httpx.URL
    ) -> StarletteResponse:
        """Change request headers and send request to target url.

        - The http version of request must be in [`SUPPORTED_HTTP_VERSIONS`][fastapi_proxy_lib.core.http.SUPPORTED_HTTP_VERSIONS].

        Args:
            request: the original client request.
            target_url: target url that request will be sent to.

        Returns:
            The response from target url.
        """
        client = self.client
        follow_redirects = self.follow_redirects

        check_result = check_http_version(request.scope, SUPPORTED_HTTP_VERSIONS)
        if check_result is not None:
            return check_result

        # 将请求头中的host字段改为目标url的host
        # 同时强制移除"keep-alive"字段和添加"keep-alive"值到"connection"字段中保持连接
        require_close, proxy_header = _change_client_header(
            headers=request.headers, target_url=target_url
        )

        # 有些方法不应该包含主体
        request_content = (
            None if request.method in _NON_REQUEST_BODY_METHODS else request.stream()
        )

        # NOTE: 不要在这里catch `client.build_request` 和 `client.send` 的异常，因为通常来说
        # - 反向代理的异常需要报 5xx 错误
        # - 而正向代理的异常需要报 4xx 错误
        proxy_request = client.build_request(
            method=request.method,
            url=target_url,
            params=request.query_params,
            headers=proxy_header,
            content=request_content,  # FIXME: 一个已知问题是，流式响应头包含'transfer-encoding': 'chunked'，但有些服务器会400拒绝这个头
            # cookies=request.cookies,  # NOTE: headers中已有的cookie优先级高，所以这里不需要
        )

        # DEBUG: 用于调试的记录
        logging.debug(
            "HTTP: client:%s ; url:%s ; head:%s",
            request.client,
            proxy_request.url,
            proxy_request.headers,
        )

        proxy_response = await client.send(
            proxy_request,
            stream=True,
            follow_redirects=follow_redirects,
        )

        tasks = BackgroundTasks()
        tasks.add_task(proxy_response.aclose)  # 添加后端任务，使其在响应完后关闭

        # 依据先前客户端的请求，决定是否要添加"connection": "close"头到响应头中以关闭连接
        # https://www.uvicorn.org/server-behavior/#http-headers
        # 如果响应头包含"connection": "close"，uvicorn会自动关闭连接
        proxy_response_headers = _change_server_header(
            headers=proxy_response.headers, require_close=require_close
        )
        return StreamingResponse(
            content=proxy_response.aiter_raw(),
            status_code=proxy_response.status_code,
            headers=proxy_response_headers,
            background=tasks,
        )

    @override
    async def proxy(*_: Any, **__: Any) -> NoReturn:
        """NotImplemented."""
        raise NotImplementedError()


class ReverseHttpProxy(BaseHttpProxy):
    '''Reverse http proxy.

    Attributes:
        client: The [`httpx.AsyncClient`](https://www.python-httpx.org/api/#asyncclient) to send http requests.
        follow_redirects: Whether follow redirects of target server.
        base_url: The target server url.

    # # Examples

    ```python
    from contextlib import asynccontextmanager
    from typing import AsyncIterator

    from fastapi import FastAPI
    from fastapi_proxy_lib.core.http import ReverseHttpProxy
    from httpx import AsyncClient
    from starlette.requests import Request

    proxy = ReverseHttpProxy(AsyncClient(), base_url="http://www.example.com/")

    @asynccontextmanager
    async def close_proxy_event(_: FastAPI) -> AsyncIterator[None]:  # (1)!
        """Close proxy."""
        yield
        await proxy.aclose()

    app = FastAPI(lifespan=close_proxy_event)

    @app.get("/{path:path}")  # (2)!
    async def _(request: Request, path: str = ""):
        return await proxy.proxy(request=request, path=path)  # (3)!

    # Then run shell: `uvicorn <your.py>:app --host http://127.0.0.1:8000 --port 8000`
    # visit the app: `http://127.0.0.1:8000/`
    # you will get the response from `http://www.example.com/`
    ```

    1. lifespan please refer to [starlette/lifespan](https://www.starlette.io/lifespan/)
    2. `{path:path}` is the key.<br>
        It allows the app to accept all path parameters.<br>
        visit <https://www.starlette.io/routing/#path-parameters> for more info.
    3. !!! info
        In fact, you only need to pass the `request: Request` argument.<br>
        `fastapi_proxy_lib` can automatically get the `path` from `request`.<br>
        Explicitly pointing it out here is just to remind you not to forget to specify `{path:path}`.
    '''

    client: httpx.AsyncClient
    follow_redirects: bool
    base_url: httpx.URL

    @override
    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        *,
        base_url: Union[httpx.URL, str],
        follow_redirects: bool = False,
    ) -> None:
        """Reverse http proxy.

        Note: please make sure `base_url` is available.
            Because when an error occurs,
            we cannot distinguish whether it is a proxy server network error, or it is a error of `base_url`.
            So, we will return 502 status_code whatever the error is.

        Args:
            client: The `httpx.AsyncClient` to send http requests. Defaults to None.<br>
                If None, will create a new `httpx.AsyncClient`,
                else will use the given `httpx.AsyncClient`.
            follow_redirects: Whether follow redirects of target server. Defaults to False.
            base_url: The target proxy server url.
        """
        self.base_url = check_base_url(base_url)
        super().__init__(client, follow_redirects=follow_redirects)

    @override
    async def proxy(  # pyright: ignore [reportIncompatibleMethodOverride]
        self, *, request: StarletteRequest, path: Optional[str] = None
    ) -> StarletteResponse:
        """Send request to target server.

        Args:
            request: `starlette.requests.Request`
            path: The path params of request, which means the path params of base url.<br>
                If None, will get it from `request.path_params`.<br>
                **Usually, you don't need to pass this argument**.

        Returns:
            The response from target server.
        """
        base_url = self.base_url

        # 只取第一个路径参数。注意，我们允许没有路径参数，这代表直接请求
        path_param: str = (
            path if path is not None else next(iter(request.path_params.values()), "")
        )

        # 将路径参数拼接到目标url上
        # e.g: "https://www.example.com/p0/" + "p1"
        # NOTE: 这里的 path_param 是不带查询参数的，且允许以 "/" 开头 (最终为/p0//p1)
        target_url = base_url.copy_with(
            path=(base_url.path + path_param)
        )  # 耗时: 18.4 µs ± 262 ns

        try:
            return await self.send_request_to_target(
                request=request, target_url=target_url
            )
        except _502_ERROR_NEED_TO_BE_CATCHED_IN_REVERSE_PROXY as e:
            # 请注意，反向代理服务器（即此实例）有义务保证:
            # 无论客户端输入的路径参数是什么，代理服务器与上游服务器之间的网络连接始终都应是可用的
            # 因此这里出现任何错误，都认为代理服务器（即此实例）的内部错误，将返回502
            msg = dedent(
                f"""\
                Error in ReverseHttpProxy().proxy():
                url: {target_url}
                request headers: {request.headers}
                """
            )  # 最好不要去查询request.body，因为可能会很大，比如在上传文件的post请求中

            return return_err_msg_response(
                _ReverseProxyServerError(
                    "Oops! Something wrong! Please contact the server maintainer!"
                ),
                status_code=starlette_status.HTTP_502_BAD_GATEWAY,
                logger=logging.exception,
                _msg=msg,
                _exc_info=e,
            )
        # NOTE: 对于反向代理服务器，我们不返回 "任何" 错误信息给客户端，因为这可能涉及到服务器内部的信息泄露


class ForwardHttpProxy(BaseHttpProxy):
    '''Forward http proxy.

    Attributes:
        client: The [`httpx.AsyncClient`](https://www.python-httpx.org/api/#asyncclient) to send http requests.
        follow_redirects: Whether follow redirects of target server.
        proxy_filter: Callable Filter, decide whether reject the proxy requests.

    # # Examples

    ```python
    from contextlib import asynccontextmanager
    from typing import AsyncIterator

    from fastapi import FastAPI
    from fastapi_proxy_lib.core.http import ForwardHttpProxy
    from fastapi_proxy_lib.core.tool import default_proxy_filter
    from httpx import AsyncClient
    from starlette.requests import Request

    proxy = ForwardHttpProxy(AsyncClient(), proxy_filter=default_proxy_filter)

    @asynccontextmanager
    async def close_proxy_event(_: FastAPI) -> AsyncIterator[None]:
        """Close proxy."""
        yield
        await proxy.aclose()

    app = FastAPI(lifespan=close_proxy_event)

    @app.get("/{path:path}")
    async def _(request: Request, path: str = ""):
        return await proxy.proxy(request=request, path=path)

    # Then run shell: `uvicorn <your.py>:app --host http://127.0.0.1:8000 --port 8000`
    # visit the app: `http://127.0.0.1:8000/http://www.example.com`
    # you will get the response from `http://www.example.com`
    ```
    '''

    client: httpx.AsyncClient
    follow_redirects: bool
    proxy_filter: ProxyFilterProto

    @override
    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        *,
        follow_redirects: bool = False,
        proxy_filter: Optional[ProxyFilterProto] = None,
    ) -> None:
        """Forward http proxy.

        Args:
            client: The `httpx.AsyncClient` to send http requests. Defaults to None.<br>
                If None, will create a new `httpx.AsyncClient`,
                else will use the given `httpx.AsyncClient`.
            follow_redirects: Whether follow redirects of target server. Defaults to False.
            proxy_filter: Callable Filter, decide whether reject the proxy requests.
                If None, will use the default filter.
        """
        # TODO: 当前显式发出警告是有意设计，后续会取消警告
        self.proxy_filter = warn_for_none_filter(proxy_filter)
        super().__init__(client, follow_redirects=follow_redirects)

    @override
    async def proxy(  # pyright: ignore [reportIncompatibleMethodOverride]
        self,
        *,
        request: StarletteRequest,
        path: Optional[str] = None,
    ) -> StarletteResponse:
        """Send request to target server.

        Args:
            request: `starlette.requests.Request`
            path: The path params of request, which means the full url of target server.<br>
                If None, will get it from `request.path_params`.<br>
                **Usually, you don't need to pass this argument**.

        Returns:
            The response from target server.
        """
        proxy_filter = self.proxy_filter

        # 只取第一个路径参数
        path_param: str = (
            next(iter(request.path_params.values()), "") if path is None else path
        )
        # 如果没有路径参数，即在正向代理中未指定目标url，则返回400
        if path_param == "":
            error = _BadTargetUrlError("Must provide target url.")
            return return_err_msg_response(
                error, status_code=starlette_status.HTTP_400_BAD_REQUEST
            )

        # 尝试解析路径参数为url
        try:
            # NOTE: 在前向代理中，路径参数即为目标url。
            # TODO: 每次实例化URL都要消耗16.2 µs，考虑是否用lru_cache来优化
            target_url = httpx.URL(path_param)
        except httpx.InvalidURL as e:  # pragma: no cover
            # 这个错误应该是不会被引起的，因为接收到的path_param是经过校验的
            # 但不排除有浏览器不遵守最大url长度限制，发出了超长的url导致InvalidURL错误
            # 所以我们在这里记录这个严重错误，表示要去除 `pragma: no cover`
            return return_err_msg_response(
                e,
                status_code=starlette_status.HTTP_400_BAD_REQUEST,
                logger=logging.critical,
            )

        # 进行请求过滤
        filter_result = proxy_filter(target_url)
        if filter_result is not None:
            return return_err_msg_response(
                _RejectedProxyRequestError(filter_result),
                status_code=starlette_status.HTTP_403_FORBIDDEN,
            )

        try:
            return await self.send_request_to_target(
                request=request, target_url=target_url
            )
        # 需要检查客户端输入的url是否合法，包括缺少scheme; 如果不合符会引发 _400 异常
        except _400_ERROR_NEED_TO_BE_CATCHED_IN_FORWARD_PROXY as e:
            return return_err_msg_response(
                e, status_code=starlette_status.HTTP_400_BAD_REQUEST
            )
        except _500_ERROR_NEED_TO_BE_CATCHED_IN_FORWARD_PROXY as e:
            # 5xx 错误需要记录
            return return_err_msg_response(
                e,
                status_code=starlette_status.HTTP_500_INTERNAL_SERVER_ERROR,
                logger=logging.exception,
                _exc_info=e,
            )
        # 请注意，我们不返回其他错误给客户端，因为这可能涉及到服务器内部的信息泄露
