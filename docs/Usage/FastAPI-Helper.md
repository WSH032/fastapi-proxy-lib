# FastAPI Helper

!!!note
    FastAPI Helper Module need `FastAPI` installed.

There are two helper modules to get FastAPI `app`/`router` for proxy conveniently.

- [fastapi_proxy_lib.fastapi.app][]: High-level
- [fastapi_proxy_lib.fastapi.router][]: Low-level

## app

use `fastapi_proxy_lib.fastapi.app` is very convenient and out of the box, there are three helper functions:

- [forward_http_app][fastapi_proxy_lib.fastapi.app.forward_http_app]
- [reverse_http_app][fastapi_proxy_lib.fastapi.app.reverse_http_app]
- [reverse_ws_app][fastapi_proxy_lib.fastapi.app.reverse_ws_app]

Example:

```python
from fastapi_proxy_lib.fastapi.app import reverse_http_app
from httpx import AsyncClient

client = AsyncClient()  # (1)!
base_url = "http://www.example.com/"  # (2)!

app = reverse_http_app(client=client, base_url=base_url)
```

1. You can pass `httpx.AsyncClient` instance:
    - if you want to customize the arguments, e.g. `httpx.AsyncClient(proxies={})`
    - if you want to reuse the connection pool of `httpx.AsyncClient`
    ---
    Or you can pass `None`(The default value), then `fastapi-proxy-lib` will create a new `httpx.AsyncClient` instance for you.
2. !!! note
    The `base_url` must end with `/`!

For other app helpers, please refer to their API references.

## router

For the following scenarios, you might prefer [fastapi_proxy_lib.fastapi.router][]:

- When you need to adjust the `app`/`router` parameters.
- When you need to [mount the proxy on a route of larger app](https://fastapi.tiangolo.com/tutorial/bigger-applications/).

**^^[Please refer to the documentation of `RouterHelper` for more information :material-file-document: ][fastapi_proxy_lib.fastapi.router.RouterHelper--examples]^^**.
