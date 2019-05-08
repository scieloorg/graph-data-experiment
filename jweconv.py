from time import time

from jwcrypto import jwe, jwk, jwt
from jwcrypto.common import base64url_encode
import ujson


class JWEConverter:
    """
    Bi-directional converter of JSON-like Python dictionary objects
    and their serialized JWE encrypted string representation,
    using a single symmetric key.
    """
    def __init__(self, octet=None, alg="A256KW", enc="A256CBC-HS512"):
        """
        Parameters
        ----------
        octet : str or None
            The key-value octet sequence in base64.
            To generate one such sequence,
            import ``jwcrypto.jwk`` and use
            ``jwcrypto.jwk.JWK(generate="oct", size=256).get_op_key()``
            or something similar with other size.
            The default behavior is to generate a random key.
        alg : str
            The algorithm to be used to encrypt the CEK
            (The JWE's ``encrypted_key`` in its JSON format)
            More information in the section 4.1.1 of RFC7516.
        enc : str
            The actual encryption algorithm.
            More information in the section 4.1.2 of RFC7516.
        """
        if octet is None:
            self.key = jwk.JWK(generate="oct", size=256)
        else:
            self.key = jwk.JWK(k=octet, kty="oct")
        self.header = {"alg": alg, "enc": enc}

    def encrypt(self, claims, exp_delta=60 * 5, nbf=None, sub=None):
        """Serialize a Python dictionary object
        into a compact JWE token string without the protected header.

        Parameters
        ----------
        claims : dict
            Data to be stored (encrypted) in the JWE.
        sub : str
            Subject identification string,
            the user ID to whom the data in the claims refer to.
            It must be defined either in the claims (``sub`` key)
            or using this parameter.
        exp_delta : int
            Duration in seconds for JWE token expiration.
        nbf : int or None
            Minimum acceptable Unix timestamp.
            Its name stands for "Not Before",
            following the RFC7519 specification (Section 4.1).
            The default value is the current timestamp of each call.
        """
        now = int(time()) # Seconds since Epoch
        token = jwt.JWT(
            header={"alg": "HS256"},
            claims=claims,
            default_claims={
                "exp": now + exp_delta,
                "nbf": nbf or now,
                "sub": sub,
            },
        )
        token.make_signed_token(self.key)
        payload = token.serialize().encode("utf-8")
        etoken = jwe.JWE(payload, header=self.header, recipient=self.key)
        jwe_dict = etoken.objects
        return ".".join(map(base64url_encode, [
            jwe_dict["encrypted_key"],
            jwe_dict["iv"],
            jwe_dict["ciphertext"],
            jwe_dict["tag"],
        ]))

    def decrypt(self, token_str, check_exp=True):
        """Convert a serialized JWE token string without its header
        into a Python dictionary with its contents.

        Parameters
        ----------
        token_str : str
            The compact JWE token string
            in its orthodox base64 representation.
            It should be a valid JWE, else this method will raise
            a ``jwcrypto.jwe.InvalidJWEData`` exception.
        check_exp : bool
            Flag telling if the "Expiration Time" (``exp``) field
            should be checked.
            When this flag is ``True``
            and the input token have already expired,
            a ``jwcrypto.jwt.JWTExpired`` exception is raised.
        """
        etoken = jwe.JWE()
        headerless_jwe = dict(zip(["encrypted_key", "iv", "ciphertext", "tag"],
                                  token_str.split(".")))
        etoken_dict = {"header": self.header, **headerless_jwe}
        etoken.deserialize(ujson.dumps(etoken_dict))
        etoken.decrypt(self.key)
        token = jwt.JWT(
            key=self.key,
            jwt=etoken.payload.decode("utf-8"),
            check_claims={"exp": None if check_exp else False,
                          "nbf": None, "sub": None},
        )
        return ujson.loads(token.claims)
