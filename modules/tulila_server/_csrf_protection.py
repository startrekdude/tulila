"""Protect an aiohttp.web Application from CSRF attacks.

This module implements a simple stateless scheme to protect an entire aiohttp.web
Application from CSRF attacks with minimal changes to the application code:
  1. A randomly-generated CSRF token will be added as a cookie to every session.
  2. Any state-changing request (POST, PUT, etc.) must include a CSRF token in
     a header or form field. This token must match the token from the cookie.

In addition to this basic protection, the application should use SameSite=Lax or
SameSite=Strict on its own cookies. Either SameSite protection or this protection
should be sufficient by itself, but defense in depth is always good. Note that
certain older browsers do not support SameSite protection; this could be an issue
if you expect lots of traffic from smart fridges.

Exports:
  - init_csrf_protection: enable CSRF protection for an Application.
  - add_csrf_token_to_jinja: a aiohttp_jinja2 context processor that exposes the CSRF
    token as a variable named "csrf_token".
A session's CSRF token is always avaiable as request["csrf_token"].
"""

from base64 import b64encode
from os import urandom

from aiohttp.web import middleware, Application, HTTPForbidden, Request, StreamResponse

from collections.abc import Awaitable, Callable, Set
from typing import Final, Optional


__all__ = (
	"add_csrf_token_to_jinja",
	"init_csrf_protection",
)


_SAFE_METHODS: Final[Set[str]] = frozenset(("GET", "HEAD", "OPTIONS", "TRACE"))
_new_csrf_token: Callable[[], str] = lambda: b64encode(urandom(16)).decode()

@middleware
async def _csrf_protection_middleware(
	request: Request,
	handler: Callable[[Request], Awaitable[StreamResponse]]
) -> StreamResponse:
	"""Reject any state-changing request that does not include the correct CSRF token.
	
	Additionally, create a CSRF token for any request sent without one; this will be
	added as a session cookie when the response is prepared.
	"""
	csrf_token: str = request.cookies.get("csrf_token", _new_csrf_token())
	request["csrf_token"] = csrf_token
	
	if request.method not in _SAFE_METHODS:
		if "X-CSRF-Token" in request.headers:
			req_csrf_token: Optional[str] = request.headers["X-CSRF-Token"]
		else:
			data = await request.post()
			form_field = data.get("csrf_token", None)
			req_csrf_token = form_field if isinstance(form_field, str) else None
		
		if req_csrf_token != csrf_token:
			return HTTPForbidden()
	
	return await handler(request)


async def _on_response_prepare_add_csrf_token(request: Request, response: StreamResponse) -> None:
	"""Attach a CSRF token to any session without one."""
	csrf_token: str = request["csrf_token"]
	if "csrf_token" not in request.cookies:
		response.headers.add(
			"Set-Cookie",
			f'csrf_token="{csrf_token}"; Path=/; HttpOnly; SameSite=Lax'
		)


async def add_csrf_token_to_jinja(request: Request) -> dict[str, str]:
	"""Make a request's CSRF token available in a Jinja2 context."""
	csrf_token: str = request["csrf_token"]
	return {"csrf_token": csrf_token}


def init_csrf_protection(app: Application) -> None:
	"""Protect an Application from CSRF attacks."""
	app.middlewares.append(_csrf_protection_middleware)
	app.on_response_prepare.append(_on_response_prepare_add_csrf_token)
