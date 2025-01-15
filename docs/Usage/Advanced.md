# Advanced

For the following scenarios, you might prefer [fastapi_proxy_lib.core][]:

- When you need to use proxies with **only** `Starlette` dependencies (without `FastAPI`).
- When you need more fine-grained control over parameters and lifespan event.
- When you need to further process the input and output before and after the proxy (similar to middleware).

We will demonstrate with `FastAPI`,
but you can completely switch to the `Starlette` approach,
which is officially supported by this project.

## Starlette Support

**^^[Please visit the `ReverseHttpProxy#examples` to view the demo with annotations :material-file-document: ][fastapi_proxy_lib.core.http.ReverseHttpProxy--examples]^^**.

Also (without annotations):

- [`ForwardHttpProxy#examples`][fastapi_proxy_lib.core.http.ForwardHttpProxy--examples]
- [`ReverseWebSocketProxy#examples`][fastapi_proxy_lib.core.websocket.ReverseWebSocketProxy--examples]

## Modify request

In some cases, you may want to make final modifications before sending a request, such as performing behind-the-scenes authentication by modifying the headers of request.

`httpx` provides comprehensive authentication support, and `fastapi-proxy-lib` offers first-class support for `httpx`.

See <https://www.python-httpx.org/advanced/#customizing-authentication>

You can refer following example to implement a simple authentication:

```python
--8<-- "docs_src/advanced/modify-request.py"
```

visit `/headers` to see the result which contains `"X-Authentication": "bearer_token"` header.

## Modify response

In some cases, you may want to make final modifications before return the response to the client, such as transcoding video response streams.

See [issue#15](https://github.com/WSH032/fastapi-proxy-lib/issues/15)

You can refer following example to modify the response:

```python
--8<-- "docs_src/advanced/modify-response.py"
```

visit `/`, you will notice that the response body is printed to the console.

## Modify (redefine) response only to particular endpoint

```python
--8<-- "docs_src/advanced/modify-response-particular.py"
```

In this example all requests except `GET /ip` will be passed to `httpbin.org`:

```bash
# we assume your proxy server is running on `http://127.0.0.0:8000`

# from `httpbin.org` which is proxied
curl http://127.0.0.0:8000/user-agent   # { "user-agent": "curl/7.81.0" }
# from your fastapi app
curl http://127.0.0.0:8000/ip           # { "msg":"Method is redefined" }
```
