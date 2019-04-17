from contextlib import asynccontextmanager
import os
import re
from urllib.parse import parse_qs, unquote, urlparse

import bonsai
from sanic import Blueprint, response


LDAP_DEFAULT_USER_FIELD = "sAMAccountName"
LDAP_DEFAULT_SEARCH_TEMPLATE = "(&(objectClass=person)({user_field}={0}))"
LDAP_PATH_FIELDS = ("admin", "user")
LDAP_PATH_REGEX = re.compile(f"/({'|'.join(LDAP_PATH_FIELDS)}|all)"
                             r"(?::|%3[Aa])([^/]*)")


bp = Blueprint(__name__)

# Avoid bug described in https://github.com/noirello/bonsai/issues/25
bonsai.set_connect_async(False)


def dsn_path_parse(path):
    """Get dict from a ``/key1:value1/key2:value2/...`` string."""
    path_dict = {k: unquote(v) for k, v in LDAP_PATH_REGEX.findall(path)}
    path_all = path_dict.get("all", "")
    return {k: ldap_join_dn(path_dict.get(k, ""), path_all)
            for k in LDAP_PATH_FIELDS}


def ldap_escape_dn(value):
    """Escape a value in a distinguished name
    to perform an LDAP bind (RFC4514)."""
    return re.sub(r'[,\\\0#+<>;"=]|^ | $', r"\\\g<0>", value)


def ldap_escape_query(value):
    """Escape a value in an LDAP search query string (RFC4515)."""
    return re.sub(r"[*\\\0)(]", r"\\\g<0>", value)


def ldap_join_dn(*args):
    """Join already escaped LDAP distinguished name parts."""
    return ",".join(filter(None, args))


class LDAPError(Exception): pass
class LDAPUserNotFound(LDAPError): pass
class LDAPBindError(LDAPError): pass
class LDAPInvalidCredentials(LDAPBindError): pass
class LDAPInvalidAdminCredentials(LDAPBindError): pass


class LDAPAuth:
    """LDAP connection authenticator.

    The DSN string should have this format::

      ldaps://<CN>:<PASS>@<HOST>/<PATH>?<QUERY>#<SEARCH_TEMPLATE>

    Given that ``<PATH>`` might be something like::

      /admin:ou=<OU>/user:ou=<OU>/all:dc=<DC>,dc=<DC>

    And the query string ``<QUERY>`` is like:

      user_field=<USER_FIELD>

    Where everything else that looks like XML tags
    are fields to be replaced.
    The common name ``<CN>`` and password ``<PASS>``
    are the ones of an "administrator",
    required in order to search a user common name
    from its "identity" filled in a ``<USER_FIELD>`` in LDAP.

    The ``<PATH>'' has a ``/''-separated blocks
    in the ``<KEY>:<VALUE>`` format.
    The key is either ``all''
    (for something to be applied on every context)
    or something in ``{LDAP_PATH_FIELDS}'', the distinct contexts.
    The values should be seen as distinguished name components
    to be glued together with the text in ``all'',
    properly escaped as a URI path
    (e.g., if the slash is part of a field,
           one can use "%2f" to avoid breaking the path parser).
    Its components might be organizational unit ``<OU>'' entries,
    domain component ``<DC>`` entries or anything else from LDAP,
    and they might appear more than once,
    separated by ``,'' following the LDAP distinguished name standard
    (each ``dn'' in path contents needs to be pre-escaped for LDAP).

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
        self.dn_suffix_map = dsn_path_parse(parsed.path)
        self.admin_dn = self.cn2dn(unquote(parsed.username), context="admin")
        self.admin_pass = unquote(parsed.password)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        self.query_dict = {
            "user_field": LDAP_DEFAULT_USER_FIELD,
            **{k: v[0] for k, v in qs.items()},
        }
        self.search_template = unquote(parsed.fragment) \
                               or LDAP_DEFAULT_SEARCH_TEMPLATE

    def cn2dn(self, cn, context="user"):
        f"""Get the distinguished name from a common name.
        The possible contexts are ``{LDAP_PATH_FIELDS}``.
        """
        return ldap_join_dn("cn=" + ldap_escape_dn(cn),
                            self.dn_suffix_map[context])

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

    async def get_user_cn(self, user):
        async with self.bind(self.admin_dn, self.admin_pass) as conn:
            result = await conn.search(
                self.dn_suffix_map["user"],
                bonsai.LDAPSearchScope.ONELEVEL,
                self.search_template.format(ldap_escape_query(user),
                                            **self.query_dict),
            )
            try:
                return result[0]["cn"][0]
            except (IndexError, KeyError):
                raise LDAPUserNotFound

    async def authenticate(self, user, password):
        try:
            dn = self.cn2dn(await self.get_user_cn(user))
        except LDAPInvalidCredentials:
            raise LDAPInvalidAdminCredentials
        async with self.bind(dn, password) as conn:
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
