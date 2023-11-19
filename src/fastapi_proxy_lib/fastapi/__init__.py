"""Module for fastapi. User-oriented helper functions.

Note: All user-oriented non-private functions (including local functions) must have documentation.
"""

from importlib.util import find_spec
from textwrap import dedent

if find_spec("fastapi") is None:  # pragma: no cover  # 无法测试
    msg = dedent(
        """\
        `fastapi` is not installed.
        `fastapi_proxy.app` module requires installing `fastapi` first:
            pip install fastapi-proxy[standard]
        """
    )
    raise RuntimeError(msg)
