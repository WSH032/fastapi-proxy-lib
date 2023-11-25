# Introduction

We provide two types of proxies:

- reverse proxy:
    - [ReverseHttpProxy][fastapi_proxy_lib.core.http.ReverseHttpProxy]
    - [ReverseWebSocketProxy][fastapi_proxy_lib.core.websocket.ReverseWebSocketProxy]
- forward proxy:
    - [ForwardHttpProxy][fastapi_proxy_lib.core.http.ForwardHttpProxy]

## What is a reverse proxy?

A reverse proxy is similar to a gateway.

All reverse proxies have a `base_url` parameter, which transparently forwards all requests sent to the proxy server to the target server specified by `base_url`.

For example, if you set `base_url` to `http://www.example.com/foo/`, and the proxy server launches at `http://127.0.0.1:8000`.

Then all requests sent to the proxy server will be forwarded to `http://www.example.com/foo/`, including `path-params`, `query-params`, `headers`, `cookies`, etc.

Visit `http//127.0.0.1:8000/bar?baz=1`, will get the response from `http://www.example.com/foo/bar?baz=1`.

## What is a forward proxy?

A forward proxy is very similar to a reverse proxy, except that the forward proxy server uses the full `path` of the requests it receives as the `base_url`.

For example, visit `http//127.0.0.1:8000/http://www.example.com/foo/bar?baz=1`, will get the response from `http://www.example.com/foo/bar?baz=1`.
