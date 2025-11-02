"""Associate an authenticated user's identity with requests.

This module provides authentication services to the rest of Tulila Server.
It is designed to encapsulate the complexities of authentication as much
as possible and expose a very simple API. This API is as follows:
  - Once, when initializing the app, call init_authentication(app).
  - Slap @requires_authentication on anything that, well, requires
    authentication.
  - In the handler, call who(request) to get the user.

The routes for logging in and out are defined here as well. Authentication
is based on a provided password, which is verified against the Argon2id
password hash stored in the database.

No server-side state is required to support user sessions - the user is
sent back a cookie containing their identity. This cookie is encrypted and,
more importantly, _authenticated_ with AES-GCM to enable the rejection of
forgeries.
"""

from base64 import b64decode, b64encode
from binascii import Error as Base64DecodeError
from contextlib import suppress
from functools import update_wrapper
from os import urandom
from time import time
from typing import NamedTuple

import cbor2 as cbor

from aiohttp.web import (
	middleware,
	AppKey,
	Application,
	HTTPFound,
	Response,
	Request,
	StreamResponse,
)
from aiohttp_jinja2 import render_template
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from Crypto.Cipher import AES
from sqlalchemy import select
from sqlalchemy.orm import Session

from ._database import database, User

from collections.abc import Awaitable, Callable
from typing import cast, ClassVar, Optional, TypedDict


__all__ = (
	"who",
	"requires_authentication",
	"init_authentication",
)


class _AuthToken(TypedDict):
	"""Represent an authentication token, including the principal and an expiry timestamp.
	
	Required to help mypy type-check successfully; this type is never instantiated.
	"""
	who: str
	exp: int


class _CheckCookieResult(NamedTuple):
	"""Represent the result of checking an auth cookie."""
	username      : Optional[str]
	should_refresh: bool  # The cookie is close to expiry and a new one should be issued.


class _Authentication:
	"""Generate and verify authentication cookies with an ephemeral key.
	
	This class contains logic to issue, verify, and re-issue authentication cookies that
	are encrypted & authenticated with a randomly-generated ephemeral key (it follows that
	cookies are not valid through a server restart; this is by design).
	
	Every authentication cookie contains the username of the authenticated user and an
	expiry timestamp (which is always a fixed amount of time after the cookie was issued.)
	
	Cookies are encrypted and authenticated with AES-GCM, providing the confidentiality
	and data origin authentication security properties. Data origin authentication is key:
	we know the signer possessed the same key, which is (should be) just us, therefore we
	can trust the claims in the cookie. Confidentiality is just nice to have: neither the
	username nor the expiry date need to be private, but there's no sense exposing the
	internal structure of the authentication mechanism to users.
	
	Upon verifying a cookie, the username of the authenticated user (if any) will be
	returned along with a boolean indicating if the cookie should be regenerated; this
	will be True if the cookie is close to expiry.
	"""
	
	_EXPIRE_AFTER     : ClassVar[int] = 3 * 60 * 60  # 3 hours
	_REISSUE_THRESHOLD: ClassVar[int] = 15 * 60      # 15 minutes
	
	def __init__(self) -> None:
		"""Create a new _Authentication with a random key."""
		self._key = urandom(16)
	
	def check_cookie(self, cookie: str) -> _CheckCookieResult:
		"""Verify an authentication cookie.
		
		Returns the username of the authenticated user (if any) and a boolean indicating
		whether the cookie should be refreshed.
		
		If the cookie cannot be verified as authentic, the returned username will be None.
		"""
		invalid_cookie = _CheckCookieResult(username=None, should_refresh=False)
		# Do not process excessively long data (light anti-DOS)
		if len(cookie) > 256:
			return invalid_cookie
		
		try:
			data = b64decode(cookie)
			
			# The cookie must be long enough to include the nonce, the tag, and some data
			if len(data) < 40:
				return invalid_cookie
			
			nonce = data[:16]
			tag   = data[16:32]
			ct    = data[32:]
			
			cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
			
			# The following raises ValueError if the tag cannot be verified
			tok: _AuthToken = cbor.loads(cipher.decrypt_and_verify(ct, tag))
			
			if tok["exp"] < int(time()):
				return invalid_cookie
			
			return _CheckCookieResult(
				username       = tok["who"],
				should_refresh = (tok["exp"] - time()) < _Authentication._REISSUE_THRESHOLD
			)
		except (Base64DecodeError, KeyError, ValueError):
			return invalid_cookie
	
	def cookie_for(self, username: str) -> str:
		"""Issue a new authentication cookie for the given username."""
		cipher = AES.new(self._key, AES.MODE_GCM)
		assert isinstance(cipher.nonce, bytes)
		
		ct, tag = cipher.encrypt_and_digest(cbor.dumps({
			"who": username,
			"exp": int(time()) + _Authentication._EXPIRE_AFTER
		}))
		val = b64encode(cipher.nonce + tag + ct).decode()
		
		return f'auth="{val}"; Max-Age={_Authentication._EXPIRE_AFTER}; Path=/; HttpOnly; SameSite=Lax'


@middleware
async def _authentication_middleware(
	request: Request,
	handler: Callable[[Request], Awaitable[StreamResponse]]
) -> StreamResponse:
	"""Add the logged-in user to the request, if any."""
	if auth := request.cookies.get("auth", None):
		username, should_refresh = request.app[_authentication].check_cookie(auth)
		if username:
			with Session(request.app[database]) as session:
				user = session.scalar(select(User).where(User.username == username))
			if user:
				request["user"] = user
				request["_should_refresh_auth_cookie"] = should_refresh
	
	return await handler(request)


async def _on_response_prepare_refresh_auth_cookie(request: Request, response: StreamResponse) -> None:
	"""Re-issue the user's authentication cookie, if required."""
	if bool(request.get("_should_refresh_auth_cookie", False)):
		response.headers.add("Set-Cookie", request.app[_authentication].cookie_for(who(request).username))


def who(request: Request) -> User:
	"""Return the user associated with the request.
	
	If there is no user associated with the request, raise an error.
	
	The primary advantage of using this function over request["user"] is that this
	function has type annotations. If you use request["user"], be prepared to
	sprinkle assert isinstance(user, User) all over your code!
	"""
	if "user" not in request:
		raise RuntimeError("there is no user associated with this request")
	return cast(User, request["user"])


def requires_authentication(
	f: Callable[[Request], Awaitable[StreamResponse]]
) -> Callable[[Request], Awaitable[StreamResponse]]:
	"""Require authentication to access a resource.
	
	This is a decorator for an aiohttp request handler. If the user is not authenticated,
	they will be redirected to the login page rather than given access to the resource.
	"""
	async def _check_auth(request: Request) -> StreamResponse:
		"""Check that the user is authenticated before allowing access."""
		if "user" not in request:
			if request.rel_url.raw_path_qs == "/":
				return HTTPFound("/login")
			else:
				return HTTPFound(f"/login?return_to={request.rel_url.raw_path_qs}")
		return await f(request)
	wrapper: Callable[[Request], Awaitable[StreamResponse]] = _check_auth
	return update_wrapper(wrapper, f)


async def _get_login(request: Request) -> Response:
	"""Display the login form."""
	if "user" in request:
		return HTTPFound(request.query.get("return_to", "/"))
	
	context = {
		"failed"    : "failed" in request.query,
		"return_to" : request.query.get("return_to", None),
	}
	return render_template("login.jinja", request, context)


async def _post_login(request: Request) -> Response:
	"""Handle an attempt to login."""
	data      = await request.post()
	username  = data.get("username", None)
	password  = data.get("password", None)
	return_to = data.get("return_to", "/")
	
	# Required in case some idiot submits a FileField for return_to
	if not isinstance(return_to, str):
		return_to = "/"
	
	if isinstance(username, str) and isinstance(password, str):
		with Session(request.app[database]) as session:
			user = session.scalar(select(User).where(User.username == username))
		
		# The argon2-cffi .verify() method returns True on success and...raises a VerifyMismatchError
		# on failure? Truly _boneheaded_ API design, I know... Suppress the error.
		with suppress(VerifyMismatchError):
			if user and PasswordHasher().verify(user.password_hash, password):
				response = HTTPFound(return_to)
				response.headers.add("Set-Cookie", request.app[_authentication].cookie_for(username))
				return response
	
	return HTTPFound(f"/login?failed=1&return_to={return_to}")


async def _post_logout(request: Request) -> Response:
	"""Handle an attempt to logout."""
	data = await request.post()
	return_to = data.get("return_to", "/")
	if not isinstance(return_to, str):
		return_to = "/"
	
	response = HTTPFound(return_to)
	if "user" in request:
		response.del_cookie("auth")
		# Do not regenerate the auth cookie for a user that is logging out,
		# even if it would otherwise be required...
		request["_should_refresh_auth_cookie"] = False
	return response


_authentication: AppKey[_Authentication] = AppKey("_authentication")

def init_authentication(app: Application) -> None:
	"""Setup authentication support for the Application."""
	app[_authentication] = _Authentication()
	app.middlewares.append(_authentication_middleware)
	app.on_response_prepare.append(_on_response_prepare_refresh_auth_cookie)
	
	app.router.add_get ("/login" , _get_login)
	app.router.add_post("/login" , _post_login)
	app.router.add_post("/logout", _post_logout)
