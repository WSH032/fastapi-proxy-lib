# Advanced and Starlette

For the following scenarios, you might prefer [fastapi_proxy_lib.core][]:

- When you need to use proxies with **only** `Starlette` dependencies (without `FastAPI`).
- When you need more fine-grained control over parameters and lifespan event.
- When you need to further process the input and output before and after the proxy (similar to middleware).

We will demonstrate with `FastAPI`,
but you can completely switch to the `Starlette` approach,
which is officially supported by this project.

**^^[Please visit the `ReverseHttpProxy#examples` to view the demo with annotations :material-file-document: ][fastapi_proxy_lib.core.http.ReverseHttpProxy--examples]^^**.

Also (without annotations):

- [`ForwardHttpProxy#examples`][fastapi_proxy_lib.core.http.ForwardHttpProxy--examples]
- [`ReverseWebSocketProxy#examples`][fastapi_proxy_lib.core.websocket.ReverseWebSocketProxy--examples]
