"""The utils tools for both http proxy and websocket proxy."""

import ipaddress
import logging
import warnings
from functools import lru_cache
from textwrap import dedent
from typing import (
    Any,
    Iterable,
    Mapping,
    Optional,
    Protocol,
    TypedDict,
    TypeVar,
    Union,
)

import httpx
from starlette import status
from starlette.background import BackgroundTask as BackgroundTask_t
from starlette.responses import JSONResponse
from starlette.types import Scope
from typing_extensions import deprecated, overload

__all__ = (
    "check_base_url",
    "return_err_msg_response",
    "check_http_version",
    "BaseURLError",
    "ErrMsg",
    "ErrRseponseJson",
    "ProxyFilterProto",
    "default_proxy_filter",
    "warn_for_none_filter",
    "lru_get_url",
    "reset_lru_get_url",
    "_RejectedProxyRequestError",
)

#################### Constant ####################


#################### Data Model ####################


_ProxyFilterTypeVar = TypeVar("_ProxyFilterTypeVar", bound="ProxyFilterProto")


class ProxyFilterProto(Protocol):
    """All proxy filter must implement like this."""

    def __call__(self, url: httpx.URL, /) -> Union[None, str]:
        """Decide whether accept the proxy request by the given url.

        Examples:
            Refer to [`default_proxy_filter`][fastapi_proxy_lib.core._tool.default_proxy_filter]

        Args:
            url: The target url of the client request to proxy.

        Returns:
            None: should accept the proxy request.
            str: should rejetc the proxy request.
                The `str` is the reason of reject.
        """


class LoggerProtocol(Protocol):
    """Like logging.error() ."""

    def __call__(
        self,
        *,
        msg: object,
        exc_info: Union[BaseException, None, bool],
    ) -> Any:
        ...


class ErrMsg(TypedDict):
    """A error message of response.

    Attributes:
        err_type: equal to {type(error).__name__}.
        msg: equal to {str(error)}.
    """

    # NOTE: `err_type` 和 `msg` 键是api设计的一部分
    err_type: str
    msg: str


class ErrRseponseJson(TypedDict):
    """A json-like dict for return by `JSONResponse`.

    Somethin like:
    ```json
    {
        "detail": {
            "err_type": "RuntimeError",
            "msg": "Something wrong."
        }
    }
    ```
    """

    # https://fastapi.tiangolo.com/tutorial/handling-errors/#httpexception
    # NOTE: `detail` 键是api设计的一部分
    detail: ErrMsg


#################### Error ####################


class BaseURLError(ValueError):
    """Invalid URL."""


"""带有 '_' 开头的错误，通常用于返回给客户端，而不是在python内部处理."""  # noqa: RUF001


class _RejectedProxyRequestError(RuntimeError):
    """Should be raised when reject proxy request."""


class _UnsupportedHttpVersionError(RuntimeError):
    """Unsupported http version."""


#################### Tools ####################


@deprecated(
    "May or may not be removed in the future.", category=PendingDeprecationWarning
)
def reset_lru_get_url(maxsize: Union[int, None] = 128, typed: bool = False) -> None:
    """Reset the parameters or clear the cache of `lru_get_url`.

    Args:
        maxsize: The same as `functools.lru_cache`.
        typed: The same as `functools.lru_cache`.
    """
    global _lru_get_url
    _lru_get_url.cache_clear()
    _lru_get_url = lru_cache(maxsize, typed)(_lru_get_url.__wrapped__)


@deprecated(
    "May or may not be removed in the future.", category=PendingDeprecationWarning
)
@lru_cache(maxsize=1024)
def _lru_get_url(url: str) -> httpx.URL:
    return httpx.URL(url)


@deprecated(
    "May or may not be removed in the future.", category=PendingDeprecationWarning
)
def lru_get_url(url: str) -> httpx.URL:
    """Lru cache for httpx.URL(url)."""
    # 因为 lru 缓存返回的是可变对象，所以这里需要复制一份
    return _lru_get_url(url).copy_with()


def check_base_url(base_url: Union[httpx.URL, str], /) -> httpx.URL:
    """Check and format base_url.

    - Time consumption: 56.2 µs ± 682 ns.

    Args:
        base_url: url that need to be checked and formatted.
            - If base_url is a str, it will be converted to httpx.URL.

    Raises:
        BaseURLError:
            - if base_url does not contain {scheme} or {netloc}.
            - if base_url does not ends with "/".

    Returns:
        `base_url.copy_with(query=None, fragment=None)`
            - The copy of original `base_url`.

    Examples:
        r = check_base_url("https://www.example.com/p0/p1?q=1")
        assert r == "https://www.example.com/p0/"

    The components of a URL are broken down like this:
        https://jo%40email.com:a%20secret@müller.de:1234/pa%20th?search=ab#anchorlink
        [scheme]   [  username  ] [password] [ host ][port][ path ] [ query ] [fragment]
                [       userinfo        ] [   netloc   ][    raw_path    ]
    """
    example_url = "https://www.example.com/path/"

    # 避免修改原来的 base_url
    base_url = (
        base_url.copy_with() if isinstance(base_url, httpx.URL) else httpx.URL(base_url)
    )

    if not base_url.scheme or not base_url.netloc:
        raise BaseURLError(
            dedent(
                f"""\
                `base_url` must contain scheme and netloc,
                e.g. {example_url}
                got: {base_url}\
                """
            )
        )

    # NOTE: 尽量用 URL.copy_with() 来修改URL，而不是 URL.join()，因为后者性能较差

    if base_url.query or base_url.fragment:
        base_url = base_url.copy_with(query=None, fragment=None)
        warnings.warn(
            dedent(
                f"""\
                `base_url` should not contain `query` or `fragment`, which will be ignored.
                The `base_url` will be treated as: {base_url}\
                """
            ),
            stacklevel=2,
        )
    # 我们在这里强制要求 base_url 以"/"结尾是有原因的:
    # 因为 RouterHelper 生成的路由是以"/"结尾的，在反向代理时
    # "/" 之后后路径参数将会被拼接到这个 base_url 后面
    if not str(base_url).endswith("/"):
        msg = dedent(
            f"""\
            `base_url` must ends with "/", may be you mean:
            {base_url}/\
            """
        )
        raise BaseURLError(msg)

    return base_url


# TODO: https://fastapi.tiangolo.com/tutorial/handling-errors/
# 使用这个引发异常让fastapi自动处理，而不是返回一个JSONResponse
# 但是这样就不能使用后台任务了
def return_err_msg_response(
    err: Union[BaseException, ErrMsg],
    /,
    *,
    # JSONResponse 参数
    status_code: int,
    headers: Optional[Mapping[str, str]] = None,
    background: Optional[BackgroundTask_t] = None,
    # logger 参数
    logger: Optional[LoggerProtocol] = None,
    _msg: Optional[Any] = None,
    _exc_info: Optional[BaseException] = None,
) -> JSONResponse:
    """Return a JSONResponse with error message and log the error message by logger.

    - logger(msg=_msg, exc_info=_exc_info)
    - JSONResponse(
        ...,
        status_code=status_code,
        headers=headers,
        background=background,
    )

    The error message like:
    ```json
    {
        "detail": {
            "err_type": "RuntimeError",
            "msg": "Something wrong."
        }
    }
    ```

    Args:
        err:
            If err is subclass of `BaseException`, it will be converted to `ErrMsg`.
            If err is a `ErrMsg`, it will be used directly.

        status_code: The status code of response.
        headers: The header of response. Defaults to None.
        background: The background task of response. Defaults to None.

        logger: Something like `logging.error`. Defaults to None.
            If it is None, will do nothing.
            If it is not None, it will be used to log error message.
        _msg: The msg to log. Defaults to None.
            If it is None, it will be set to `JSONResponse` content.
        _exc_info: The detailed error info to log. Defaults to None.
            If it is None, will do nothing.
            If it is not None, will be passed to logger.

    Raises:
        TypeError: If err is not a BaseException or ErrMsg.

    Returns:
        JSONResponse about error message.
    """
    if isinstance(err, BaseException):
        detail = ErrMsg(err_type=type(err).__name__, msg=str(err))
    else:
        detail = err

    err_response_json = ErrRseponseJson(detail=detail)

    # TODO: 请注意，logging是同步函数，每次会阻塞1ms左右，这可能会导致性能问题
    # 特别是对于写入文件的log，最好把它放到 asyncio.to_thread 里执行
    # https://docs.python.org/zh-cn/3/library/asyncio-task.html#coroutine

    if logger is not None:
        # 只要传入了logger，就一定记录日志
        logger(
            msg=_msg
            if _msg is not None
            else err_response_json,  # 如果没有指定 _msg ，则使用content
            exc_info=_exc_info,
        )
    else:
        # 如果没有传入logger，但传入了非None的_msg或_exc_info（即代表使用者可能希望记录log），则发出警告
        if _msg is not None or _exc_info is not None:
            warnings.warn(
                "You should pass logger to record error message, "
                "or you can ignore this warning if you don't want to record error message.",
                stacklevel=2,
            )

    return JSONResponse(
        content=err_response_json,
        status_code=status_code,
        headers=headers,  # pyright: ignore[reportGeneralTypeIssues] # 这似乎是starlette的注解错误，因为实际是只用Mapping就可以
        background=background,
    )


def check_http_version(
    scope: Scope, supported_versions: Iterable[str]
) -> Union[JSONResponse, None]:
    """Check whether the http version of scope is in supported_versions.

    Args:
        scope: asgi scope dict.
        supported_versions: The supported http versions.

    Returns:
        If the http version of scope is not in supported_versions, return a JSONResponse with status_code=505,
        else return None.
    """
    # https://asgi.readthedocs.io/en/latest/specs/www.html#http-connection-scope
    # https://asgi.readthedocs.io/en/latest/specs/www.html#websocket-connection-scope
    http_version: str = scope.get("http_version", "")
    # 如果明确指定了http版本（即不是""），但不在支持的版本内，则返回505
    if http_version not in supported_versions and http_version != "":
        error = _UnsupportedHttpVersionError(
            f"The request http version is {http_version}, but we only support {supported_versions}."
        )
        # TODO: 或许可以logging记录下 scope.get("client") 的值
        return return_err_msg_response(
            error,
            status_code=status.HTTP_505_HTTP_VERSION_NOT_SUPPORTED,
            logger=logging.info,
        )


def default_proxy_filter(url: httpx.URL) -> Union[None, str]:
    """Filter by host.

    If the host of url is ip address, which is not global ip address, then will reject it.

    Warning:
        It will consumption time: 3.22~4.7 µs ± 42.6 ns.

    Args:
        url: The target url of the client request to proxy.

    Returns:
        None: should accept the proxy request.
        str: should rejetc the proxy request.
            The `str` is the reason of reject.
    """
    try:
        ip_address = ipaddress.ip_address(url.host)
    except ValueError:
        return None

    if not ip_address.is_global:
        return "Deny proxy for non-public IP addresses."

    return None


@overload
def warn_for_none_filter(proxy_filter: _ProxyFilterTypeVar) -> _ProxyFilterTypeVar:
    ...


@overload
def warn_for_none_filter(proxy_filter: None) -> ProxyFilterProto:
    ...


def warn_for_none_filter(
    proxy_filter: Union[ProxyFilterProto, None]
) -> ProxyFilterProto:
    """Check whether the argument `proxy_filter` is None.

    Args:
        proxy_filter: The argument need to be check.

    Returns:
        If proxy_filter is None, will warn user and return `default_proxy_filter`.
    Else will just return the original argument `proxy_filter`.
    """
    if proxy_filter is None:
        msg = dedent(
            """\
            The proxy filter is None, which means no filter will be used.
            This is not recommended, because it may cause security issues.

            A default proxy filter will be used, which will reject the proxy request:
             - if the host of url is ip address, and is not global ip address.
            """
        )
        warnings.warn(msg, stacklevel=3)
        return default_proxy_filter
    else:
        return proxy_filter
