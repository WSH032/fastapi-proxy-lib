from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import AsyncContentStream, StreamingResponse

from fastapi_proxy_lib.core.http import ReverseHttpProxy

proxy = ReverseHttpProxy(base_url="http://www.example.com/")


@asynccontextmanager
async def close_proxy_event(_: FastAPI) -> AsyncIterator[None]:
    """Close proxy."""
    yield
    await proxy.aclose()


app = FastAPI(lifespan=close_proxy_event)


async def new_content(origin_content: AsyncContentStream) -> AsyncContentStream:
    """Fake content processing."""
    async for chunk in origin_content:
        # do some processing with chunk, e.g transcoding,
        # here we just print and return it as an example.
        print(chunk)
        yield chunk


@app.get("/{path:path}")
async def _(request: Request, path: str = ""):
    proxy_response = await proxy.proxy(request=request, path=path)

    if isinstance(proxy_response, StreamingResponse):
        # get the origin content stream
        old_content = proxy_response.body_iterator

        new_resp = StreamingResponse(
            content=new_content(old_content),
            status_code=proxy_response.status_code,
            headers=proxy_response.headers,
            media_type=proxy_response.media_type,
        )
        return new_resp

    return proxy_response
