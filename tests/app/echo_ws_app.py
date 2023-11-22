# ruff: noqa: D100
# pyright: reportUnusedFunction=false

import asyncio

from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect

from .tool import AppDataclass4Test, RequestDict


def get_app() -> AppDataclass4Test:  # noqa: C901, PLR0915
    """Get the echo ws app.

    Returns:
        TestAppDataclass.
    """
    app = FastAPI()
    request_dict = RequestDict(request=None)
    test_app_dataclass = AppDataclass4Test(app=app, request_dict=request_dict)

    @app.websocket_route("/echo_text")
    async def echo_text(websocket: WebSocket):
        """Websocket endpoint for echo text. Just receive text and send it back.

        Note: client must send text first.
        """
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = websocket

        await websocket.accept()
        while True:
            try:
                recev = await websocket.receive_text()
                await websocket.send_text(recev)
            except WebSocketDisconnect:
                break

    @app.websocket_route("/echo_bytes")
    async def echo_bytes(websocket: WebSocket):
        """Websocket endpoint for echo bytes. Just receive bytes and send it back.

        Note: client must send bytes first.
        """
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = websocket

        await websocket.accept()
        while True:
            try:
                recev = await websocket.receive_bytes()
                await websocket.send_bytes(recev)
            except WebSocketDisconnect:
                break

    @app.websocket_route("/accept_foo_subprotocol")
    async def accept_foo_subprotocol(websocket: WebSocket):
        """When client send subprotocols request, if subprotocols contain "foo", will accept it."""
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = websocket

        # https://asgi.readthedocs.io/en/latest/specs/www.html#websocket-connection-scope
        if "foo" in websocket.scope["subprotocols"]:
            accepted_subprotocol = "foo"
        else:
            accepted_subprotocol = None

        await websocket.accept(subprotocol=accepted_subprotocol)

        await websocket.close()

    @app.websocket_route("/just_close_with_1001")
    async def just_close_with_1001(websocket: WebSocket):
        """Just do nothing after `accept`, then close ws with 1001 code."""
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = websocket

        await websocket.accept()
        await asyncio.sleep(0.3)
        await websocket.close(1001)

    @app.websocket_route("/reject_handshake")
    async def reject_handshake(websocket: WebSocket):
        """Will reject ws request by just calling `websocket.close()`."""
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = websocket

        await websocket.close()

    @app.websocket_route("/do_nothing")
    async def do_nothing(websocket: WebSocket):
        """Will do nothing except `websocket.accept()`."""
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = websocket

        await websocket.accept()

    return test_app_dataclass


# for cmd test
app = get_app().app
