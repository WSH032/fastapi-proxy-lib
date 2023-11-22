"""The data model for both http proxy and websocket proxy."""

import abc
from typing import (
    Any,
    Optional,
)

from httpx import AsyncClient

__all__ = ("BaseProxyModel",)


class BaseProxyModel(abc.ABC):
    """Http proxy base ABC class.

    Attributes:
        client: The httpx.AsyncClient to send http requests.
        follow_redirects: Whether follow redirects of proxy server.
    """

    client: AsyncClient
    follow_redirects: bool

    def __init__(
        self, client: Optional[AsyncClient] = None, *, follow_redirects: bool = False
    ) -> None:
        """Http proxy base class.

        Args:
            client: The httpx.AsyncClient to send http requests. Defaults to None.
                if None, will create a new httpx.AsyncClient,
                else will use the given httpx.AsyncClient.
            follow_redirects: Whether follow redirects of proxy server. Defaults to False.
        """
        self.client = client if client is not None else AsyncClient()
        self.follow_redirects = follow_redirects

    async def aclose(self) -> None:
        """Close AsyncClient.

        Equal to:
            await self.client.aclose()
        """
        await self.client.aclose()

    @abc.abstractmethod
    async def send_request_to_target(self, *args: Any, **kwargs: Any) -> Any:
        """Abstract method to send request to target server.

        Subclass must implement this method.
            - Should accept orinal request from client, such as starlette.requests.Request | starlette.websockets.WebSocket .
            - Then adjust the request, e.g change the host of request to target proxy server.
            - Then sent the request to target proxy server.
            - Response:
                - If is http proxy response, should return starlette.responses.Response.
                - If is websocket proxy, just establish the connection between client and target server.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def proxy(self, *args: Any, **kwargs: Any) -> Any:
        """A user-facing high-level method that encapsulates the `self.send_request_to_target()` method.

        Receives the raw incoming parameters from the app,
        processes the parameters before passing them to the `self.send_request_to_target()` method,
        or independently determines the specific internal implementation.
        Its return value should be consistent with that of send_request_to_target.
        """
        raise NotImplementedError()
