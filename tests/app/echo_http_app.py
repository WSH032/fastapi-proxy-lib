# ruff: noqa: D100, D417
# pyright: reportUnusedFunction=false

import io
from typing import Literal, Mapping, Union

from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from .tool import AppDataclass4Test, RequestDict

DEFAULT_FILE_NAME = "echo.txt"


def get_app() -> AppDataclass4Test:
    """Get the echo http app.

    Returns:
        TestAppDataclass.
    """
    app = FastAPI()
    request_dict = RequestDict(request=None)
    test_app_dataclass = AppDataclass4Test(app=app, request_dict=request_dict)

    @app.head("/head/return_keep_alive_headers")
    async def return_keep_alive_headers(request: Request) -> Response:
        """Http head method endpoint.

        Returns:
            A response of which headers has:
                - Connection: keep-alive
                - Keep-Alive: timeout=5, max=1000
        """
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = request
        return Response(
            headers={"Connection": "keep-alive", "Keep-Alive": "timeout=5, max=1000"}
        )

    @app.head("/head/return_close_connection_headers")
    async def return_close_connection_headers(request: Request) -> Response:
        """Http head method endpoint.

        Returns:
            A response of which headers contains `{"Connection": "close"}`.
        """
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = request
        return Response(headers={"Connection": "close"})

    @app.head("/head/return_none_connection_headers")
    async def return_none_connection_headers(request: Request) -> Response:
        """Http head method endpoint.

        Returns:
            A response of which headers contains `{"Connection": "close"}`.
        """
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = request
        return Response(headers={})

    @app.get("/get/echo_headers_and_params")
    async def echo_headers_and_params(
        request: Request,
    ) -> Mapping[str, Union[str, Mapping[str, str]]]:
        """Http get method endpoint for echo headers, path_params, query_params.

        Returns:
            ```py
            {
                **request.headers,
                "path_params": request.path_params,
                "query_params": request.query_params,
            }
            ```
        """
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = request
        msg = {
            **request.headers,
            "path_params": request.path_params,
            "query_params": request.query_params,
        }
        return msg

    @app.post("/post/echo_body")
    async def echo_body(request: Request) -> Response:
        """Http post method endpoint for echo body.

        Returns:
            A response of which body is the same as request body.
        """
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = request
        return Response(content=await request.body())

    @app.put("/put/echo_file")
    async def echo_file(request: Request, content: str = "") -> StreamingResponse:
        """Http put method endpoint for echo file.

        Args:
            content: The content of file to echo.

        Returns:
            A response of file StreamingResponse
            - body: file stream of which content is `/put/echo_file?content={content}`.
            - Headers:
                - Media-Type: `text/plain; charset=utf-8`
                - Content-Disposition: `attachment; filename=echo.txt`
        """
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = request
        txt_file_like = io.BytesIO(content.encode("utf-8"))
        return StreamingResponse(
            txt_file_like,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename={DEFAULT_FILE_NAME}"
            },
        )

    @app.options("/")
    async def options_endpoint(request: Request) -> Response:
        """Http options method endpoint.

        Returns:
            A response of which headers contains `{"Allow": "GET, POST, PUT, OPTIONS, HEAD, DELETE, PATCH"}`.
        """
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = request
        return Response(
            headers={"Allow": "GET, POST, PUT, OPTIONS, HEAD, DELETE, PATCH"}
        )

    @app.get("/")
    @app.post("/")
    @app.put("/")
    @app.head("/")
    @app.delete("/")
    @app.patch("/")
    async def _(request: Request) -> Literal[0]:
        nonlocal test_app_dataclass
        test_app_dataclass.request_dict["request"] = request
        return 0

    return test_app_dataclass


# for cmd test
app = get_app().app
