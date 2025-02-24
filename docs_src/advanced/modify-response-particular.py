from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.requests import Request

from fastapi_proxy_lib.core.http import ReverseHttpProxy

proxy = ReverseHttpProxy(base_url="http://httpbin.org/")


@asynccontextmanager
async def close_proxy_event(_: FastAPI) -> AsyncIterator[None]:
    """Close proxy."""
    yield
    await proxy.aclose()


app = FastAPI(lifespan=close_proxy_event)


@app.get("/{path:path}")
@app.post("/{path:path}")
async def _(request: Request, path: str = ""):
    if path == "ip" and request.method == "GET":
        return {"msg": "Method is redefined"}
    else:
        return await proxy.proxy(request=request, path=path)
