# ruff: noqa: ANN201, ANN001

# pyright: reportMissingParameterType=false
# 返回值标注太麻烦，让pyright自己推断

"""Pytest fixtures for the tests."""

# https://anyio.readthedocs.io/en/stable/testing.html

import typing
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import (
    AsyncIterator,
    Callable,
    Coroutine,
    Literal,
    Optional,
    Protocol,
)

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from fastapi_proxy_lib.fastapi.app import (
    forward_http_app,
    reverse_http_app,
    reverse_ws_app,
)
from typing_extensions import ParamSpec

from .app.echo_http_app import get_app as get_http_test_app
from .app.echo_ws_app import get_app as get_ws_test_app
from .app.tool import AppDataclass4Test, AutoServer

# ASGI types.
# Copied from: https://github.com/florimondmanca/asgi-lifespan/blob/fbb0f440337314be97acaae1a3c0c7a2ec8298dd/src/asgi_lifespan/_types.py
Scope = typing.MutableMapping[str, typing.Any]
Message = typing.MutableMapping[str, typing.Any]
Receive = typing.Callable[[], typing.Awaitable[Message]]
Send = typing.Callable[[Message], typing.Awaitable[None]]
ASGIApp = typing.Callable[[Scope, Receive, Send], typing.Awaitable[None]]


_P = ParamSpec("_P")


@dataclass
class LifeAppDataclass4Test(AppDataclass4Test):
    """Test app with lifespan dataclass.

    Attributes:
        app: The asgi app for test.
        request_dict: use `request["request"]` to get the latest original http/websocket request from the client.
    """

    app: ASGIApp  # pyright: ignore[reportIncompatibleVariableOverride]


LifespanManagerFixture = typing.Callable[[ASGIApp], Coroutine[None, None, ASGIApp]]
AppFactoryFixture = Callable[..., Coroutine[None, None, ASGIApp]]
"""The lifespan of app will be managed automatically by pytest."""


class AutoServerFixture(Protocol):  # noqa: D101
    def __call__(  # noqa: D102
        self,
        app: FastAPI,
        host: str,
        port: int,
        server_type: Optional[Literal["uvicorn", "hypercorn"]] = None,
    ) -> Coroutine[None, None, AutoServer]: ...


# https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on
@pytest.fixture(
    params=[
        pytest.param(("asyncio", {"use_uvloop": False}), id="asyncio"),
        pytest.param(
            ("trio", {"restrict_keyboard_interrupt_to_checkpoints": True}), id="trio"
        ),
    ],
)
def anyio_backend(request: pytest.FixtureRequest):
    """Specify the async backend for `pytest.mark.anyio`."""
    return request.param


@pytest.fixture()
async def lifespan_manager() -> AsyncIterator[LifespanManagerFixture]:
    """Fixture for asgi lifespan manager.

    Returns:
        _lifespan_manager: (LifespanManagerFixture)
    """
    async with AsyncExitStack() as exit_stack:

        async def _lifespan_manager(app: ASGIApp) -> ASGIApp:
            """Manage lifespan event for app.

            Args:
                app: The app of which lifespan event need to be managed.

            Returns:
                ASGIApp: The app with lifespan event managed.
            """
            nonlocal exit_stack
            manager = await exit_stack.enter_async_context(LifespanManager(app))
            return manager.app

        yield _lifespan_manager


# TestAppDataclass 设计的时候，TestAppDataclass.request 只存取最新的一个请求
# 所以这里明确要求每个fixture的作用域都是"function"，不要共享 TestAppDataclass


@pytest.fixture()
async def echo_http_test_model(
    lifespan_manager: LifespanManagerFixture,
) -> LifeAppDataclass4Test:
    """Echo http app for test.

    Returns:
        LifeAppDataclass4Test: refer to `test.app.echo_http_app.get_app()`.
            LifeAppDataclass4Test.app: The echo http app for test
            def LifeAppDataclass4Test.request(): Get the latest original http request from the client
    """
    app_dataclass = get_http_test_app()
    life_app = await lifespan_manager(app_dataclass.app)
    return LifeAppDataclass4Test(app=life_app, request_dict=app_dataclass.request_dict)


@pytest.fixture()
async def echo_ws_test_model(
    lifespan_manager: LifespanManagerFixture,
) -> LifeAppDataclass4Test:
    """Echo ws app for test.

    Returns:
        LifeAppDataclass4Test: refer to `test.app.echo_ws_app.get_app()`.
            LifeAppDataclass4Test.app: The echo ws app for test
            def LifeAppDataclass4Test.request(): Get the latest original http request from the client
    """
    app_dataclass = get_ws_test_app()
    life_app = await lifespan_manager(app_dataclass.app)
    return LifeAppDataclass4Test(app=life_app, request_dict=app_dataclass.request_dict)


def _app_fct_life_wapper(  # noqa: D417
    app_fct: Callable[_P, ASGIApp], lifespan_manager_fixture: LifespanManagerFixture
) -> Callable[_P, Coroutine[None, None, ASGIApp]]:
    """A wrapper for app factory function.

    Make the lifespan event of the app returned by `app_fct()` be managed automatically by pytest.

    Args:
        app_fct: The app factory function which need to be wrapped.

    Returns:
        The wrapped app factory function.
    """

    async def wappered_app_fct(*args: _P.args, **kwargs: _P.kwargs) -> ASGIApp:
        """Return an app with lifespan event managed automatically by pytest."""
        app = app_fct(*args, **kwargs)
        return await lifespan_manager_fixture(app)

    return wappered_app_fct


@pytest.fixture()
def forward_http_app_fct(
    lifespan_manager: LifespanManagerFixture,
):  # -> AppFactoryFixture
    """Return wrapped `fastapi_proxy_lib.fastapi.app.forward_http_app()`.

    The lifespan of app returned by original `forward_http_app()` will be managed automatically by pytest.
    """
    return _app_fct_life_wapper(forward_http_app, lifespan_manager)


@pytest.fixture()
def reverse_http_app_fct(
    lifespan_manager: LifespanManagerFixture,
):  # -> AppFactoryFixture
    """Return wrapped `fastapi_proxy_lib.fastapi.app.reverse_http_app()`.

    The lifespan of app returned by original `reverse_http_app()` will be managed automatically by pytest.
    """
    return _app_fct_life_wapper(reverse_http_app, lifespan_manager)


@pytest.fixture()
def reverse_ws_app_fct(
    lifespan_manager: LifespanManagerFixture,
):  # -> AppFactoryFixture
    """Return wrapped `fastapi_proxy_lib.fastapi.app.reverse_ws_app()`.

    The lifespan of app returned by original `reverse_ws_app()` will be managed automatically by pytest.
    """
    return _app_fct_life_wapper(reverse_ws_app, lifespan_manager)


@pytest.fixture()
async def auto_server_fixture() -> AsyncIterator[AutoServerFixture]:
    """Fixture for AutoServer.

    Will launch and shutdown automatically.
    """
    async with AsyncExitStack() as exit_stack:

        async def auto_server_fct(
            app: FastAPI,
            host: str,
            port: int,
            server_type: Optional[Literal["uvicorn", "hypercorn"]] = None,
        ) -> AutoServer:
            auto_server = await exit_stack.enter_async_context(
                AutoServer(app=app, host=host, port=port, server_type=server_type)
            )
            return auto_server

        yield auto_server_fct
