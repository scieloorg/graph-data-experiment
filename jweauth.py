from functools import update_wrapper
from time import time

from jwcrypto.jwe import InvalidJWEData
from jwcrypto.jwt import JWTExpired, JWTNotYetValid
from sanic import response

from jweconv import JWEConverter


class UnknownAuthorizationHeader(Exception): pass
class NoAuthorizationHeader(Exception): pass


def get_auth_token(request):
    auth_prefix = "Bearer "
    auth_header = request.headers.get("Authorization", "")
    if auth_header and not auth_header.startswith(auth_prefix):
        raise UnknownAuthorizationHeader
    return auth_header[len(auth_prefix):]


class SanicJWEAuth:
    """
    Authentication and authorization based on JWE tokens.
    """
    def __init__(self, app, authenticate, *, auth_exceptions, realm,
        octet=None,
        auth_fields={"username": "sub", "password": "p"},
        route="/auth",
        session_fields={"username": "sub"},
        session_request_key="session",
        session_duration=60 * 60 * 24 * 30,
        token_duration=60 * 5,
    ):
        """
        Parameters
        ----------
        app : sanic.Sanic or sanic.Blueprint
            The Sanic application/blueprint object
            where the handlers for authorization and refreshing
            should be added.
        authenticate : coroutine function
            Async/coroutine function that performs authentication,
            returning user data as a dict to be merged in the tokens
            after transforming it with ``session_fields``.
            It should raise an exception when the authentication fails.
        auth_exceptions : iterable containing classes
            All exceptions that the given ``authenticate`` might raise
            to tell that the authentication failed.
        realm : str
            A case-sensitive string defining the protection space,
            to be shown in HTTP 401 errors.
        octet : str or None
            The key-value octet sequence in base64 for a symmetric key
            stored in JWK, as required by ``jweconv.JWEConverter``.
        auth_fields : dict
            Map of authentication fields.
            Its keys are the names of the fields
            that should appear in the POST request
            to authenticate for the first time,
            the keywords to call ``authenticate``.
            Its values are where the credentials should be stored
            in the JWE token (its internal claims, based on JWT),
            and ``"sub"`` (some user ID) must be part of these.
        session_fields: dict
            Map of session fields.
            Its keys are how the field is returned by ``authenticate``
            and how it'll appear in ``request[session_request_key]``.
            Its values are the keys where this data should be stored
            in the token.
            If it overlaps the authentication credentials,
            the ``authenticate`` result for the overlapping fields
            will get replaced by the authentication inputs.
            The ``authenticate`` don't need to return every field,
            the default value for missing fields is ``None``.
        route : str
            Route for authentication (POST) and token refreshing (GET).
        session_request_key : str
            Key in the request object of a handler
            where the ``require_authorization`` decorator
            should store the JWE contents.
        session_duration : int
            Duration in seconds for disabling JWE token refreshing.
        token_duration : int
            Duration in seconds for expiration of a single JWE token.
        """
        if "sub" not in auth_fields.values():
            raise ValueError('Missing "sub" user identification field')
        if "exp" in auth_fields.values() or "nbf" in auth_fields.values() \
                                         or "exp" in session_fields.values() \
                                         or "nbf" in session_fields.values():
            raise ValueError('Overwriting a default claim ("exp"/"nbf")')
        self.authenticate = authenticate
        self.auth_exceptions = tuple(auth_exceptions)
        self.realm = realm
        self.jc = JWEConverter(octet)
        self.auth_fields = auth_fields
        self.session_fields = session_fields
        self.session_request_key = session_request_key
        self.session_duration = session_duration
        self.token_duration = token_duration
        app.add_route(self.get_handler, route, methods=["GET"])
        app.add_route(self.post_handler, route, methods=["POST"])

    def get_jwe(self, request, check_exp=True):
        """Get the dictionary with the contents in the JWE token
        stored in the Authorization header of a request.
        For more information about ``check_exp``,
        see the ``jweconv.JWEConverter.decrypt method`` docs.

        Raises
        ------
        NoAuthorizationHeader
            No ``Authorization: ...`` header line in the request.
        UnknownAuthorizationHeader
            Authorization header isn't a bearer token.
        jwcrypto.jwe.InvalidJWEData
            The bearer token isn't a JWE token.
        jwcrypto.jwt.JWTExpired
            Token had already expired.
        jwcrypto.jwt.JWTNotYetValid
            The token "nbf" (Not Before) claim is before now.
        jwcrypto.jwt.JWTMissingClaim
            A required field ("sub"/"exp"/"nbf") isn't in the token.
        """
        access_token = get_auth_token(request)
        if not access_token:
            raise NoAuthorizationHeader
        return self.jc.decrypt(access_token, check_exp=check_exp)

    def unauthorized(self, **kwargs):
        """Create a HTTP 401 response with a single Bearer challenge
        defined in its WWW-Authenticate header.
        The keyword arguments are mapped as header parameters.
        """
        challenge = ", ".join(
            k + '="' + v.replace('"', r'\"') + '"'
            for k, v in {"realm": self.realm, **kwargs}.items()
        )
        return response.json({"error": "unauthorized"},
            status=401,
            headers={"WWW-Authenticate": "Bearer " + challenge}
        )

    def require_authorization(self, *args, check_exp=True):
        """Decorator to restrict access to a handler.
        This function works both as a parametrized decorator
        and as non-parametrized decorator.
        For more information about ``check_exp``,
        see the ``jweconv.JWEConverter.decrypt method`` docs.
        """
        def decorator(afunc):
            async def handler_wrapper(request, *args, **kwargs):
                try:
                    jwe = self.get_jwe(request, check_exp=check_exp)
                except (NoAuthorizationHeader, UnknownAuthorizationHeader):
                    return self.unauthorized()
                except JWTNotYetValid:
                    return self.unauthorized(error="unsynchronized")
                except (InvalidJWEData, JWTExpired):
                    return self.unauthorized(error="invalid_token")
                session = {k: jwe.get(v, None)
                           for k, v in self.session_fields.items()}
                request[self.session_request_key] = session
                return await afunc(request, *args, **kwargs)
            return update_wrapper(handler_wrapper, afunc)
        return decorator(*args) if args else decorator

    async def create_jwe(self, auth_kwargs, nbf=None):
        """Authenticate and return a compact JWE for this session.

        Parameters
        ----------
        auth_kwargs : dict
            Keyword arguments for ``authenticate`` function.
        nbf : int or None
            Unix timestamp of the first JWE creation.
            It should be ``None`` when authenticating,
            but it should have the content of the previous "nbf" field
            when refreshing.

        The ``authenticate`` function may abort this generation
        by means of an exception.
        """
        user_data = await self.authenticate(**auth_kwargs)
        session_jwe = {self.session_fields[k]: v for k, v in user_data.items()
                                                 if k in self.session_fields}
        auth_jwe = {self.auth_fields[k]: v for k, v in auth_kwargs.items()}
        return self.jc.encrypt({**session_jwe, **auth_jwe},
                               exp_delta=self.token_duration,
                               nbf=nbf)

    async def create_response(self, auth_kwargs, nbf=None):
        """Authenticate and return a Sanic response object.
        See ``create_jwe`` for more information about the parameters.
        This method already deals with the ``authenticate`` exceptions.
        """
        try:
            token = await self.create_jwe(auth_kwargs, nbf=nbf)
        except self.auth_exceptions:
            return self.unauthorized()
        return response.json({
            "access_token": token,
            "token_type": "bearer",
            "expires_in": self.token_duration,
        })

    async def post_handler(self, request):
        """Handler of the authentication route."""
        payload = request.json
        if not payload or set(payload.keys()) != set(self.auth_fields.keys()):
            return response.json({"error": "bad_request"}, status=400)
        return await self.create_response(payload)

    async def get_handler(self, request):
        """Handler of the refresh route."""
        try:
            jwe = self.get_jwe(request, check_exp=False)
        except (NoAuthorizationHeader, UnknownAuthorizationHeader):
            return self.unauthorized()
        except JWTNotYetValid:
            return self.unauthorized(error="unsynchronized")
        except InvalidJWEData:
            return self.unauthorized(error="invalid_token")
        if time() - jwe["nbf"] > self.session_duration:
            return self.unauthorized(error="invalid_token")
        auth_kwargs = {k: jwe[v] for k, v in self.auth_fields.items()}
        return await self.create_response(auth_kwargs, nbf=jwe["nbf"])
