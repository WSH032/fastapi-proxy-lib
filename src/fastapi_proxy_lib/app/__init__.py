"""Module for fastapi app."""

import logging
from importlib.util import find_spec
from textwrap import dedent

if find_spec("fastapi") is None:
    msg = dedent(
        """\
        `fastapi` is not installed.
        `fastapi_proxy.app` module requires installing `fastapi` first:
            pip install fastapi-proxy[standard]
        """
    )
    logging.critical(msg)
