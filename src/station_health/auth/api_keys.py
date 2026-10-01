"""API-key authentication with per-route roles, documented in OpenAPI."""

import functools
import hmac
from collections.abc import Callable
from typing import Any, TypeVar

from flask import request
from flask_smorest import Api, Blueprint

from station_health.auth.roles import Role
from station_health.errors import abort
from station_health.runtime import current_settings

API_KEY_HEADER = "X-API-Key"
SECURITY_SCHEME = "ApiKeyAuth"

View = TypeVar("View", bound=Callable[..., Any])


def register_security_scheme(api: Api) -> None:
    api.spec.components.security_scheme(
        SECURITY_SCHEME, {"type": "apiKey", "in": "header", "name": API_KEY_HEADER}
    )


def require_role(blp: Blueprint, role: Role) -> Callable[[View], View]:
    """Reject the request with 401 (no valid key) or 403 (key lacks `role`).

    Apply it above the blueprint's argument decorators, so a caller learns about a
    missing key before anything about their payload.
    """

    def decorator(view: View) -> View:
        @functools.wraps(view)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            roles = _roles_for(request.headers.get(API_KEY_HEADER, ""))
            if roles is None:
                abort(401, f"A valid API key is required in the {API_KEY_HEADER} header.")
            if role not in roles:
                abort(403, f"This API key does not have the '{role}' role.")
            return view(*args, **kwargs)

        documented = blp.doc(security=[{SECURITY_SCHEME: []}])(guarded)
        documented = blp.alt_response(401, response="UNAUTHORIZED")(documented)
        documented = blp.alt_response(403, response="FORBIDDEN")(documented)
        return documented  # type: ignore[no-any-return]

    return decorator


def _roles_for(presented: str) -> frozenset[Role] | None:
    if not presented:
        return None
    match = None
    # Compare against every key in constant time, so timing reveals nothing about which matched.
    for key, roles in current_settings().api_keys.items():
        if hmac.compare_digest(key.encode(), presented.encode()):
            match = roles
    return match
