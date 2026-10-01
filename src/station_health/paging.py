"""Cursor paging shared by the list endpoints.

A cursor is opaque to clients: base64url JSON of the sort key of a page's last item.
"""

import base64
import binascii
import json
from typing import Any

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500


class InvalidCursor(ValueError):
    pass


def encode_cursor(key: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    """The key a cursor holds. Raises InvalidCursor unless it decodes to a JSON object."""
    try:
        key = json.loads(base64.urlsafe_b64decode(cursor))
    except (binascii.Error, ValueError) as error:
        raise InvalidCursor from error
    if not isinstance(key, dict):
        raise InvalidCursor
    return key
