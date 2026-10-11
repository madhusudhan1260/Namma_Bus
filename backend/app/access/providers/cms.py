"""
Minimal CMS / PKCS#7 SignedData verifier for PDF digital signatures (adbe.pkcs7.detached / ETSI.CAdES.detached).

Only what is needed to check a document signature is implemented: parse SignedData (DER or BER with indefinite
lengths), find the signer certificate, check the messageDigest attribute against the signed bytes, verify the
signature over the signed attributes, and build the certificate chain to a trusted root. Uses `cryptography` only.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

OID_SIGNED_DATA = "1.2.840.113549.1.7.2"
OID_MESSAGE_DIGEST = "1.2.840.113549.1.9.4"
OID_SIGNING_TIME = "1.2.840.113549.1.9.5"
DIGESTS = {
    "1.3.14.3.2.26": (hashlib.sha1, hashes.SHA1()),
    "2.16.840.1.101.3.4.2.1": (hashlib.sha256, hashes.SHA256()),
    "2.16.840.1.101.3.4.2.2": (hashlib.sha384, hashes.SHA384()),
    "2.16.840.1.101.3.4.2.3": (hashlib.sha512, hashes.SHA512()),
}


class CmsError(Exception):
    pass


# ---------------------------------------------------------------------------
# Tiny BER/DER reader
# ---------------------------------------------------------------------------

@dataclass
class Node:
    tag: int
    start: int  # offset of the tag byte
    content_start: int
    end: int  # offset just past this element (including end-of-contents for indefinite lengths)
    content_end: int
    data: bytes

    @property
    def raw(self) -> bytes:
        return self.data[self.start : self.end]

    @property
    def content(self) -> bytes:
        return self.data[self.content_start : self.content_end]

    @property
    def constructed(self) -> bool:
        return bool(self.tag & 0x20)

    def children(self) -> List["Node"]:
        out, i = [], self.content_start
        while i < self.content_end:
            if self.data[i : i + 2] == b"\x00\x00":  # end-of-contents of an indefinite parent
                break
            n = read(self.data, i)
            out.append(n)
            i = n.end
        return out


def read(data: bytes, i: int = 0) -> Node:
    if i + 2 > len(data):
        raise CmsError("Truncated signature data.")
    start, tag = i, data[i]
    if tag & 0x1F == 0x1F:
        raise CmsError("Unsupported ASN.1 tag.")
    i += 1
    first = data[i]
    i += 1
    if first == 0x80:  # indefinite length (BER)
        if not tag & 0x20:
            raise CmsError("Invalid indefinite-length primitive.")
        j = i
        while True:
            if data[j : j + 2] == b"\x00\x00":
                return Node(tag, start, i, j + 2, j, data)
            j = read(data, j).end
    if first & 0x80:
        n = first & 0x7F
        length = int.from_bytes(data[i : i + n], "big")
        i += n
    else:
        length = first
    if i + length > len(data):
        raise CmsError("Truncated signature data.")
    return Node(tag, start, i, i + length, i + length, data)


def oid(node: Node) -> str:
    b = node.content
    parts = [b[0] // 40, b[0] % 40]
    value = 0
    for byte in b[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(value)
            value = 0
    return ".".join(map(str, parts))


def octets(node: Node) -> bytes:
    """OCTET STRING content (handles BER constructed octet strings)."""
    if node.constructed:
        return b"".join(octets(c) for c in node.children())
    return node.content


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _reencode_set(node: Node) -> bytes:
    """signedAttrs are signed as a DER SET OF (tag 0x31) even though they are stored as [0] IMPLICIT."""
    body = b"".join(c.raw for c in node.children())
    return b"\x31" + _der_len(len(body)) + body


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@dataclass
class SignatureInfo:
    signer: x509.Certificate
    chain: List[x509.Certificate]  # signer first, trusted root last
    signing_time: Optional[datetime]
    digest_algorithm: str


def _parse_time(node: Node) -> Optional[datetime]:
    text = node.content.decode("ascii", "ignore")
    for fmt in ("%y%m%d%H%M%SZ", "%Y%m%d%H%M%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _verify_sig(cert: x509.Certificate, signature: bytes, data: bytes, hash_alg) -> None:
    key = cert.public_key()
    try:
        if isinstance(key, rsa.RSAPublicKey):
            key.verify(signature, data, padding.PKCS1v15(), hash_alg)
        elif isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(signature, data, ec.ECDSA(hash_alg))
        else:
            raise CmsError("Unsupported signer key type.")
    except InvalidSignature:
        raise CmsError("The digital signature does not match the document.")


def _build_chain(signer: x509.Certificate, pool: List[x509.Certificate], anchors: List[x509.Certificate],
                 at: datetime) -> List[x509.Certificate]:
    chain, current = [signer], signer
    for _ in range(8):
        for anchor in anchors:
            if anchor.subject == current.issuer:
                try:
                    current.verify_directly_issued_by(anchor)
                except (ValueError, TypeError, InvalidSignature):
                    continue
                chain.append(anchor)
                for c in chain:
                    if not (c.not_valid_before_utc <= at <= c.not_valid_after_utc):
                        raise CmsError("A certificate in the signature chain was not valid when the document was signed.")
                return chain
        issuer = None
        for cand in pool:
            if cand.subject == current.issuer and cand not in chain:
                try:
                    current.verify_directly_issued_by(cand)
                except (ValueError, TypeError, InvalidSignature):
                    continue
                issuer = cand
                break
        if issuer is None:
            break
        chain.append(issuer)
        current = issuer
    raise CmsError("The signer certificate does not chain to a trusted certifying authority.")


def verify_detached(cms_der: bytes, signed_bytes: bytes, anchors: List[x509.Certificate],
                    now: Optional[datetime] = None, pinned: Optional[List[x509.Certificate]] = None) -> SignatureInfo:
    """`pinned`: certificates published by the signer's owner (e.g. UIDAI); a signer whose public key equals one of
    them is trusted directly, without building a CA chain."""
    root = read(cms_der)
    kids = root.children()
    if len(kids) < 2 or oid(kids[0]) != OID_SIGNED_DATA:
        raise CmsError("Not a CMS SignedData signature.")
    signed_data = kids[1].children()[0]  # [0] EXPLICIT
    parts = signed_data.children()
    certs: List[x509.Certificate] = []
    signer_infos = None
    for p in parts[3:]:
        if p.tag == 0xA0:  # certificates [0] IMPLICIT
            for c in p.children():
                try:
                    certs.append(x509.load_der_x509_certificate(c.raw))
                except ValueError:
                    continue
        elif p.tag == 0x31:
            signer_infos = p
    if signer_infos is None or not signer_infos.children():
        raise CmsError("The signature has no signer.")
    si = signer_infos.children()[0].children()
    sid, digest_alg_node = si[1], si[2]
    idx = 3
    signed_attrs = None
    if si[idx].tag == 0xA0:
        signed_attrs = si[idx]
        idx += 1
    signature = octets(si[idx + 1])

    digest_oid = oid(digest_alg_node.children()[0])
    if digest_oid not in DIGESTS:
        raise CmsError("Unsupported digest algorithm.")
    digest_fn, hash_alg = DIGESTS[digest_oid]

    # Signer certificate: issuerAndSerialNumber or subjectKeyIdentifier
    signer = None
    if sid.tag == 0x30:
        serial = int.from_bytes(sid.children()[1].content, "big", signed=True)
        issuer_der = sid.children()[0].raw
        for c in certs:
            if c.serial_number == serial and c.issuer.public_bytes() == issuer_der:
                signer = c
                break
    elif sid.tag == 0x80:
        for c in certs:
            try:
                if c.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value.digest == sid.content:
                    signer = c
                    break
            except x509.ExtensionNotFound:
                continue
    if signer is None:
        raise CmsError("The signer certificate is not included in the signature.")

    signing_time = None
    if signed_attrs is not None:
        message_digest = None
        for attr in signed_attrs.children():
            a_oid = oid(attr.children()[0])
            value = attr.children()[1].children()[0]
            if a_oid == OID_MESSAGE_DIGEST:
                message_digest = value.content
            elif a_oid == OID_SIGNING_TIME:
                signing_time = _parse_time(value)
        if message_digest is None or message_digest != digest_fn(signed_bytes).digest():
            raise CmsError("The document was changed after it was signed.")
        _verify_sig(signer, signature, _reencode_set(signed_attrs), hash_alg)
    else:
        _verify_sig(signer, signature, signed_bytes, hash_alg)

    at = signing_time or now or datetime.now(timezone.utc)
    signer_key = signer.public_key().public_numbers()
    for pin in pinned or []:
        if pin.public_key().public_numbers() == signer_key:
            if not (pin.not_valid_before_utc <= at <= pin.not_valid_after_utc):
                raise CmsError("The signing certificate was not valid when the document was signed.")
            return SignatureInfo(signer=signer, chain=[signer], signing_time=signing_time, digest_algorithm=digest_oid)
    chain = _build_chain(signer, certs, anchors, at)
    return SignatureInfo(signer=signer, chain=chain, signing_time=signing_time, digest_algorithm=digest_oid)
