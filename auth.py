from contextlib import asynccontextmanager
import os
import re
from urllib.parse import parse_qs, unquote, urlparse

import bonsai
from sanic import Blueprint, response


LDAP_DEFAULT_USER_FIELD = "sAMAccountName"
LDAP_DEFAULT_SEARCH_TEMPLATE = "(&(objectClass=person)({user_field}={0}))"


bp = Blueprint(__name__)

# Avoid bug described in https://github.com/noirello/bonsai/issues/25
bonsai.set_connect_async(False)


def ldap_escape_dn(value):
    """Escape a value in a distinguished name
    to perform an LDAP bind (RFC4514)."""
    return re.sub(r'[,\\\0#+<>;"=]|^ | $', r"\\\g<0>", value)


def ldap_escape_query(value):
    """Escape a value in an LDAP search query string (RFC4515)."""
    return re.sub(r"[*\\\0)(]", r"\\\g<0>", value)


class LDAPError(Exception): pass
class LDAPUserNotFound(LDAPError): pass
class LDAPBindError(LDAPError): pass
class LDAPInvalidCredentials(LDAPBindError): pass
class LDAPInvalidAdminCredentials(LDAPBindError): pass


class LDAPAuth:
    """LDAP connection authenticator.

    The DSN string should have this format::

      ldaps://<DN>:<PASS>@<HOST>/<SEARCH_DN>?<QUERY>#<SEARCH_TEMPLATE>

    Given that query string ``<QUERY>`` is like:

      user_field=<USER_FIELD>

    Where everything else that looks like XML tags
    are fields to be replaced.
    The distinguished name ``<DN>`` and password ``<PASS>``
    are the ones of an "administrator",
    required in order to search a user distinguished name
    from its "identity" filled in a ``<USER_FIELD>`` in LDAP.

    The ``<HOST>`` is simply the host name for the connection,
    which will happen in the port 636, with SSL.
    To avoid SSL,
    you can use ``ldap'' as the scheme/protocol instead of ``ldaps'',
    but that's not recommended.

    The default ``<USER_FIELD>`` is ``{LDAP_DEFAULT_USER_FIELD}``.
    It's used by the default ``<SEARCH_TEMPLATE>'',
    ``{LDAP_DEFAULT_SEARCH_TEMPLATE}''.
    This template, if customized,
    can access any data in the query string.
    """
    def __init__(self, dsn):
        parsed = urlparse(dsn)
        self.url = f"{parsed.scheme}://{parsed.hostname}"
        self.search_dn = unquote(parsed.path)[1:] # Strip leading "/"
        self.admin_dn = unquote(parsed.username)
        self.admin_pass = unquote(parsed.password)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        self.query_dict = {
            "user_field": LDAP_DEFAULT_USER_FIELD,
            **{k: v[0] for k, v in qs.items()},
        }
        self.search_template = unquote(parsed.fragment) \
                               or LDAP_DEFAULT_SEARCH_TEMPLATE

    @asynccontextmanager
    async def bind(self, dn, password):
        client = bonsai.LDAPClient(self.url)
        client.set_cert_policy("allow") # TODO: Add certificate
        client.set_credentials("SIMPLE", user=dn, password=password)
        try:
            async with client.connect(is_async=True) as conn:
                yield conn
        except bonsai.AuthenticationError as exc:
            raise LDAPInvalidCredentials from exc

    async def get_user_dn(self, user):
        async with self.bind(self.admin_dn, self.admin_pass) as conn:
            result = await conn.search(
                self.search_dn,
                bonsai.LDAPSearchScope.ONELEVEL,
                self.search_template.format(ldap_escape_query(user),
                                            **self.query_dict),
            )
            try:
                return str(result[0]["dn"])
            except (IndexError, KeyError):
                raise LDAPUserNotFound

    async def authenticate(self, user, password):
        try:
            dn = await self.get_user_dn(user)
        except LDAPInvalidCredentials:
            raise LDAPInvalidAdminCredentials
        async with self.bind(dn, password):
            return None


LDAPAuth.__doc__ = LDAPAuth.__doc__.format(**globals())
ldap = LDAPAuth(os.environ["LDAP_DSN"])


@bp.route("/auth", methods=["POST"])
async def post_auth(request):
    payload = request.json
    try:
        await ldap.authenticate(
            user=payload["uid"],
            password=payload["password"],
        )
        return response.json({"auth": True})
    except LDAPError as exc:
        reason = "_".join(re.findall("[A-Z][^A-Z]+",
                                     type(exc).__name__)).lower()
    return response.json({
        "auth": False,
        "error": "unauthorized",
        "reason": reason,
    }, status=401)
