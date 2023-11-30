# Security

## proxy requests filter in forward proxy

Forward proxy allows access to any URL on input, which can be **scary** 😫 if not restricted.

For example, through `http://www.my-proxy-server.com/http://127.0.0.1:8000`,
an attacker can access the server's local network.

So, there is a `proxy_filter` argument in [`ForwardHttpProxy`][fastapi_proxy_lib.core.http.ForwardHttpProxy.__init__] to filter requests.

If you do not explicitly specify it, `ForwardHttpProxy` will issue a warning and specify a [default_proxy_filter][fastapi_proxy_lib.core.tool.default_proxy_filter].

- If you want to accept all proxy requests (**never do this on a public server**), you can do it like this:

    ```python
    proxy_filter = lambda *_: None
    ```

- If you want to implement your own proxy filter, please refer to the [fastapi_proxy_lib.core.tool.ProxyFilterProto][].

## `http`/`ws` vs `https`/`wss`

!!! danger
    **Never use a server with the HTTPS protocol to proxy a target server (`base_url`) with the HTTP protocol !**

    e.g. `https://www.my-proxy-server.com/http://www.example.com/`

    There is a security issue:

    Browsers may send sensitive HTTPS information to your HTTPS proxy server,
    then because of transparency feature, `fastapi-proxy-lib` will forward
    these information to the target server using the HTTP protocol without modification,
    which may cause privacy leaks.

!!! failure
    If you reverse it. Use an HTTP server to proxy an HTTPS target server.

    There is a high probability that the request will fail.

## The same-origin policy of `ForwardHttpProxy`

The `ForwardHttpProxy` server uses the same source to proxy different target servers. e.g:

> http://www.my-proxy-server.com/http://www.example.com/<br>
> http://www.my-proxy-server.com/http://www.google.com/
>
> both source are `http://www.my-proxy-server.com/`

For this situation, the browser's same-origin protection policy will fail,
and cookies from `http://www.example.com/` will be sent to` http://www.google.com/`.

You should inform the user of this situation and let them decide whether to continue.

---

## What did `fastapi-proxy-lib` do to protect your Security? 🔐

!!! info
    The following content is the security measures taken by `fastapi-proxy-lib` behind the scenes.
    You may not need to read these for using this library.

### Forbid the merging of cookies at the AsyncClient level

For fix security vulnerabilities of cookies leakage between different users:

- Before sending each proxy request, `fastapi-proxy-lib` will clear `AsyncClient.cookies` to avoid recording cookies from different users.
- To prevent `AsyncClient` merge cookie, `fastapi-proxy-lib` will forcibly add an empty cookie string `""` to each proxy request that does not contain a cookie field header.

Through these, `fastapi-proxy-lib` hopes to prevent the mergence and sharing of cookies from different users.

More info, please visit [Security Advisories `GHSA-7vwr-g6pm-9hc8`](https://github.com/WSH032/fastapi-proxy-lib/security/advisories/GHSA-7vwr-g6pm-9hc8) and [#10](https://github.com/WSH032/fastapi-proxy-lib/pull/10).

!!! note
    It will **not affect** the normal sending and receiving of cookies.
