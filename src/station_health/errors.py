"""HTTP errors in the service's one JSON error shape: {code, status, message, errors?}."""

from typing import NoReturn

from flask_smorest import abort as _smorest_abort


def abort(status_code: int, message: str) -> NoReturn:
    """Stop the request with an error response. Typed `NoReturn`, unlike flask-smorest's."""
    _smorest_abort(status_code, message=message)
    raise AssertionError("unreachable")  # pragma: no cover
