"""Module for [`fastapi`](https://fastapi.tiangolo.com/).

User-oriented helper functions.
"""

# NOTE: All user-oriented non-private functions (including local functions) must have documentation.

from importlib.util import find_spec
from textwrap import dedent

if find_spec("fastapi") is None:  # pragma: no cover  # 无法测试
    msg: str = dedent(
        """\
        `fastapi` is not installed.
        `fastapi_proxy_lib.fastapi` module requires installing `fastapi` first:
            pip install fastapi-proxy-lib[standard]
        """
    )
    raise RuntimeError(msg)
