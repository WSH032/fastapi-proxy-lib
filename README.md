# FastAPI Proxy Lib

<p align="center">
    <em>HTTP/WebSocket proxy for starlette/FastAPI</em>
</p>

|         |                                                                                                                                                     |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| CI/CD   | [![CI: lint-test]][CI: lint-test#link] [![CI: docs]][CI: docs#link]                                                                                 |
| Code    | [![codecov]][codecov#link] [![Code style: black]][Code style: black#link] [![Ruff]][Ruff#link] [![Checked with pyright]][Checked with pyright#link] |
| Package | [![Python-Version]][Python-Version#link]                                                                                                            |
| Meta    | [![Hatch project]][Hatch project#link] [![GitHub License]][GitHub License#link]                                                                     |

---

Documentation: <https://wsh032.github.io/fastapi-proxy-lib/>

Source Code: <https://github.com/WSH032/fastapi-proxy-lib/>

---

## Features

- [X] **Out of the box !** [Helper functions](#quick-start) to get FastAPI `app`/`router` for proxy conveniently.
- [x] **Only `Starlette` is required** for it to work ([`FastAPI` is optional](#installation)).
- [x] Support both **HTTP** and **WebSocket** proxy.
    - [x] Supports all HTTP methods (`GET`, `POST`, etc.)
- [x] Support both **reverse** proxy and **forward** proxy.
- [x] **Transparently** and **losslessly** handle all proxy requests,
- [x] Asynchronous streaming transfer, support **file proxy**.

### other features

- [x] Strict linting and strict-mode Pyright type checking.
- [x] **100%** [Type Completeness](https://microsoft.github.io/pyright/#/typed-libraries?id=type-completeness), [Code coverage of **over 95%**][codecov#link].
- [x] Forced keep-alive connections, minimizing proxy latency.
- [x] Handle errors as gracefully as possible.

### `FastAPI Proxy Lib` stands on the shoulders of giants

- [httpx](https://github.com/encode/httpx) for HTTP proxy
- [httpx-ws](https://github.com/frankie567/httpx-ws) for WebSocket proxy

So, it perfectly supports all features of [httpx.AsyncClient](https://www.python-httpx.org/advanced/#client-instances), you can even use your custom `AsyncClient`, [`Transport`](https://www.python-httpx.org/advanced/#custom-transports).

## Installation

> !!! note
>
>     We follow semantic versioning.<br>
>     This is a young project, and before 1.0.0, there may be changes in the API (though we try to avoid that).<br>
>     We recommend pinning to any minor versions, such as 0.1.x.

Pypi will come soon, please install from github temporarily:

```shell
pip install fastapi-proxy-lib[standard]@git+https://github.com/WSH032/fastapi-proxy-lib.git
```

Perhaps you've noticed that we're installing `fastapi-proxy-lib[standard]` instead of `fastapi-proxy-lib`. The difference is:

- The former will install `FastAPI` at the same time.
- The latter installs only the basic dependencies for `fastapi-proxy-lib`.

If you **only need to use this library with Starlette**, you only need to install the latter.

## Quick start

With the helper functions, get the FastAPI proxy server app is very convenient and out of the box:

```python
from fastapi_proxy_lib.fastapi.app import reverse_http_app

app = reverse_http_app(base_url="http://www.example.com/foo/")
```

That's all! Now, you can launch the proxy server with `uvicorn`:

```shell
uvicorn main:app  --host 127.0.0.1 --port 8000
```

Then, visit `http://127.0.0.1:8000/bar?baz=1`, you will get the response from `http://www.example.com/foo/bar?baz=1`.

For support with `FastAPI router` or only using `Starlette`, please **visit to our [documentation 📚](https://wsh032.github.io/fastapi-proxy-lib/) for more details**.

## development

- If you find any issues, please don't hesitate to [open an issue](https://github.com/WSH032/fastapi-proxy-lib/issues).
- If you need assistance, feel free to [start a discussion](https://github.com/WSH032/fastapi-proxy-lib/discussions).
- [Welcome PR](https://github.com/WSH032/fastapi-proxy-lib/pulls)

English is not the native language of the author (me), so if you find any areas for improvement in the documentation, your feedback is welcome.

If you think this project helpful, consider giving it a star ![GitHub Repo stars](https://img.shields.io/github/stars/wsh032/fastapi-proxy-lib?style=social)
 , which makes me happy. :smile:

## License

This project is licensed under the terms of the *Apache License 2.0*.

<!-- link -->

[CI: lint-test]: https://github.com/WSH032/fastapi-proxy-lib/actions/workflows/lint-test.yml/badge.svg?branch=main
[CI: lint-test#link]: https://github.com/WSH032/fastapi-proxy-lib/actions/workflows/lint-test.yml
[CI: docs]: https://github.com/WSH032/fastapi-proxy-lib/actions/workflows/docs.yml/badge.svg?branch=main
[CI: docs#link]: https://github.com/WSH032/fastapi-proxy-lib/actions/workflows/docs.yml
[Python-Version]: https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2FWSH032%2Ffastapi-proxy%2Fmain%2Fpyproject.toml&logo=python&logoColor=gold&label=Python
[Python-Version#link]: https://github.com/WSH032/fastapi-proxy-lib/blob/main/pyproject.toml
[Code style: black]: https://img.shields.io/badge/code%20style-black-000000.svg
[Code style: black#link]: https://github.com/psf/black
[GitHub License]: https://img.shields.io/github/license/WSH032/fastapi-proxy-lib?color=9400d3
[GitHub License#link]: https://github.com/WSH032/fastapi-proxy-lib/blob/main/LICENSE
[Ruff]: https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json
[Ruff#link]: https://github.com/astral-sh/ruff
[Checked with pyright]: https://microsoft.github.io/pyright/img/pyright_badge.svg
[Checked with pyright#link]: https://microsoft.github.io/pyright
[Hatch project]: https://img.shields.io/badge/%F0%9F%A5%9A-Hatch-4051b5.svg
[Hatch project#link]: https://github.com/pypa/hatch
[codecov]: https://codecov.io/gh/WSH032/fastapi-proxy-lib/graph/badge.svg?token=62QQU06E8X
[codecov#link]: https://codecov.io/gh/WSH032/fastapi-proxy-lib
