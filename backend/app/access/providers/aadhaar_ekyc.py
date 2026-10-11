"""
UIDAI Aadhaar Paperless Offline e-KYC verification.

The resident downloads the e-KYC ZIP from https://myaadhaar.uidai.gov.in (Offline e-KYC) and protects it with a
4-digit share code they choose. The ZIP holds one XML file digitally signed by UIDAI. This module:

  1. opens the ZIP with the share code (WinZip AES or classic ZipCrypto),
  2. parses the XML safely (no entities, no network),
  3. checks UIDAI's enveloped XML-DSig signature against UIDAI's public certificate (ACCESS_UIDAI_CERT_PATH),
  4. checks that the file was generated recently (ACCESS_EKYC_MAX_AGE_HOURS),
  5. returns only what the app needs: name, date of birth, gender and the signed photo.

The Aadhaar number never appears in the file except as the last 4 digits inside `referenceId`; those are
used only transiently (in a keyed hash that stops one Aadhaar being used on several accounts) and never stored.
The share code, ZIP and XML are discarded after verification. Without a configured UIDAI certificate nothing is
ever marked VERIFIED.
"""

import base64
import copy
import hashlib
import hmac
import io
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from lxml import etree

DSIG = "http://www.w3.org/2000/09/xmldsig#"
NS = {"ds": DSIG}
DIGESTS = {
    "http://www.w3.org/2000/09/xmldsig#sha1": hashlib.sha1,
    "http://www.w3.org/2001/04/xmlenc#sha256": hashlib.sha256,
    "http://www.w3.org/2001/04/xmldsig-more#sha256": hashlib.sha256,
}
SIGNATURES = {
    "http://www.w3.org/2000/09/xmldsig#rsa-sha1": hashes.SHA1(),
    "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256": hashes.SHA256(),
}
C14N = {
    "http://www.w3.org/TR/2001/REC-xml-c14n-20010315": (False, False),
    "http://www.w3.org/TR/2001/REC-xml-c14n-20010315#WithComments": (False, True),
    "http://www.w3.org/2001/10/xml-exc-c14n#": (True, False),
    "http://www.w3.org/2001/10/xml-exc-c14n#WithComments": (True, True),
}
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
MAX_XML_BYTES = 2 * 1024 * 1024
TIMEZONE_IST = timezone(timedelta(hours=5, minutes=30))


class EkycError(Exception):
    """A user-facing failure with a stable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class EkycResult:
    name: str
    date_of_birth: Optional[date]
    gender: str  # M | F | T
    photo_jpeg: Optional[bytes]
    generated_at: datetime
    last4: str  # transient; never persist
    name4: str = ""  # first 4 letters of the name in capitals (as used in the e-Aadhaar PDF password)

    def __post_init__(self):
        if not self.name4:
            self.name4 = name_letters(self.name)


# ---------------------------------------------------------------------------
# ZIP: WinZip AES (AE-1/AE-2) or classic ZipCrypto, password = share code
# ---------------------------------------------------------------------------

def _aes_ctr_le(key: bytes, data: bytes) -> bytes:
    """WinZip AES uses CTR mode with a little-endian counter starting at 1."""
    blocks = (len(data) + 15) // 16
    counters = b"".join((i + 1).to_bytes(16, "little") for i in range(blocks))
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    stream = enc.update(counters) + enc.finalize()
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream[: len(data)], "big")).to_bytes(len(data), "big")


def _aes_extra(extra: bytes) -> Optional[tuple]:
    i = 0
    while i + 4 <= len(extra):
        hid, size = struct.unpack("<HH", extra[i : i + 4])
        if hid == 0x9901 and size >= 7:
            _version, _vendor, strength, method = struct.unpack("<H2sBH", extra[i + 4 : i + 11])
            return strength, method
        i += 4 + size
    return None


def _read_aes_member(raw: bytes, info: zipfile.ZipInfo, password: bytes) -> bytes:
    sig, = struct.unpack("<I", raw[info.header_offset : info.header_offset + 4])
    if sig != 0x04034B50:
        raise EkycError("BAD_FILE", "The file is not a valid ZIP archive.")
    name_len, extra_len = struct.unpack("<HH", raw[info.header_offset + 26 : info.header_offset + 30])
    start = info.header_offset + 30 + name_len + extra_len
    local_extra = raw[info.header_offset + 30 + name_len : start]
    aes = _aes_extra(local_extra) or _aes_extra(info.extra)
    if not aes:
        raise EkycError("BAD_FILE", "Unsupported ZIP encryption.")
    strength, method = aes
    key_len = {1: 16, 2: 24, 3: 32}.get(strength)
    if not key_len:
        raise EkycError("BAD_FILE", "Unsupported ZIP encryption strength.")
    salt_len = key_len // 2
    body = raw[start : start + info.compress_size]
    salt, verifier, encrypted, auth = body[:salt_len], body[salt_len : salt_len + 2], body[salt_len + 2 : -10], body[-10:]
    derived = hashlib.pbkdf2_hmac("sha1", password, salt, 1000, 2 * key_len + 2)
    enc_key, mac_key, check = derived[:key_len], derived[key_len : 2 * key_len], derived[2 * key_len :]
    if not hmac.compare_digest(check, verifier):
        raise EkycError("BAD_SHARE_CODE", "The share code is incorrect for this file.")
    if not hmac.compare_digest(hmac.new(mac_key, encrypted, hashlib.sha1).digest()[:10], auth):
        raise EkycError("BAD_FILE", "The file is damaged (integrity check failed).")
    plain = _aes_ctr_le(enc_key, encrypted)
    if method == 0:
        return plain
    if method == 8:
        return zlib.decompressobj(-15).decompress(plain, MAX_XML_BYTES + 1)
    raise EkycError("BAD_FILE", "Unsupported ZIP compression.")


def extract_xml(zip_bytes: bytes, share_code: str) -> bytes:
    if not re.fullmatch(r"\d{4}", share_code or ""):
        raise EkycError("BAD_SHARE_CODE", "The share code is the 4-digit number you chose when downloading the file.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise EkycError("BAD_FILE", "Upload the Offline e-KYC .zip file downloaded from the UIDAI website.")
    members = [i for i in zf.infolist() if i.filename.lower().endswith(".xml") and not i.is_dir()]
    if len(members) != 1 or members[0].file_size > MAX_XML_BYTES:
        raise EkycError("BAD_FILE", "This ZIP does not look like a UIDAI Offline e-KYC file.")
    info, password = members[0], share_code.encode()
    if info.compress_type == 99:
        data = _read_aes_member(zip_bytes, info, password)
    else:
        try:
            data = zf.read(info, pwd=password)
        except RuntimeError:
            raise EkycError("BAD_SHARE_CODE", "The share code is incorrect for this file.")
        except (zipfile.BadZipFile, zlib.error, NotImplementedError):
            raise EkycError("BAD_FILE", "The file could not be opened.")
    if len(data) > MAX_XML_BYTES:
        raise EkycError("BAD_FILE", "The e-KYC file is too large.")
    return data


# ---------------------------------------------------------------------------
# XML signature (enveloped XML-DSig, as used by UIDAI)
# ---------------------------------------------------------------------------

def _parse(xml: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False, remove_comments=False)
    try:
        return etree.fromstring(xml, parser)
    except etree.XMLSyntaxError:
        raise EkycError("BAD_FILE", "The e-KYC XML could not be read.")


def _standalone(el: etree._Element) -> etree._ElementTree:
    """Copy a sub-element into its own document, declaring every namespace in scope at that point.

    libxml2's sub-tree C14N wrongly emits xmlns="" on descendants of an element carrying an empty attribute
    (such as Reference URI=""), so a sub-element is never canonicalized in place.
    """
    if el.getparent() is None:
        return etree.ElementTree(el)
    root = etree.Element(el.tag, attrib=dict(el.attrib), nsmap=el.nsmap)
    root.text = el.text
    for child in el:
        root.append(copy.deepcopy(child))
    return etree.ElementTree(root)


def _c14n(el, algorithm: str) -> bytes:
    if algorithm not in C14N:
        raise EkycError("BAD_SIGNATURE", "Unsupported signature canonicalization.")
    exclusive, comments = C14N[algorithm]
    return etree.tostring(_standalone(el), method="c14n", exclusive=exclusive, with_comments=comments)


def load_certificate(path: str):
    data = Path(path).read_bytes()
    try:
        return x509.load_pem_x509_certificate(data)
    except ValueError:
        return x509.load_der_x509_certificate(data)


def verify_signature(root: etree._Element, certificate) -> None:
    signatures = root.findall("ds:Signature", NS)
    if len(signatures) != 1:
        raise EkycError("BAD_SIGNATURE", "The file is not signed by UIDAI.")
    sig = signatures[0]
    signed_info = sig.find("ds:SignedInfo", NS)
    refs = signed_info.findall("ds:Reference", NS) if signed_info is not None else []
    if signed_info is None or len(refs) != 1 or refs[0].get("URI") not in ("", None):
        raise EkycError("BAD_SIGNATURE", "Unexpected signature structure.")
    ref = refs[0]
    transforms = [t.get("Algorithm") for t in ref.findall("ds:Transforms/ds:Transform", NS)]
    if ENVELOPED not in transforms or any(t not in (ENVELOPED, *C14N) for t in transforms):
        raise EkycError("BAD_SIGNATURE", "Unexpected signature transforms.")
    c14n_ref = next((t for t in transforms if t in C14N), "http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    digest_fn = DIGESTS.get(ref.find("ds:DigestMethod", NS).get("Algorithm"))
    if digest_fn is None:
        raise EkycError("BAD_SIGNATURE", "Unsupported digest algorithm.")

    # 1. digest of the whole document without the Signature element (enveloped transform)
    doc = etree.fromstring(etree.tostring(root))
    doc.remove(doc.find("ds:Signature", NS))
    digest = base64.b64encode(digest_fn(_c14n(doc, c14n_ref)).digest()).decode()
    expected = "".join((ref.findtext("ds:DigestValue", namespaces=NS) or "").split())
    if not hmac.compare_digest(digest, expected):
        raise EkycError("BAD_SIGNATURE", "The file has been modified after UIDAI signed it.")

    # 2. RSA signature over the canonical SignedInfo
    method = signed_info.find("ds:SignatureMethod", NS).get("Algorithm")
    hash_alg = SIGNATURES.get(method)
    if hash_alg is None:
        raise EkycError("BAD_SIGNATURE", "Unsupported signature algorithm.")
    c14n_si = signed_info.find("ds:CanonicalizationMethod", NS).get("Algorithm")
    value = base64.b64decode("".join((sig.findtext("ds:SignatureValue", namespaces=NS) or "").split()))
    try:
        certificate.public_key().verify(value, _c14n(signed_info, c14n_si), padding.PKCS1v15(), hash_alg)
    except InvalidSignature:
        raise EkycError("BAD_SIGNATURE", "The UIDAI signature is not valid.")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _parse_dob(value: str) -> Optional[date]:
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def verify_ekyc(zip_bytes: bytes, share_code: str, cert_path: str, max_age_hours: int, now: Optional[datetime] = None) -> EkycResult:
    if not cert_path or not Path(cert_path).exists():
        raise EkycError("UNAVAILABLE", "Aadhaar e-KYC verification is not configured on this server yet.")
    xml = extract_xml(zip_bytes, share_code)
    root = _parse(xml)
    if etree.QName(root).localname != "OfflinePaperlessKyc":
        raise EkycError("BAD_FILE", "This is not a UIDAI Offline e-KYC file.")
    verify_signature(root, load_certificate(cert_path))

    ref = root.get("referenceId") or ""
    m = re.fullmatch(r"(\d{4})(\d{14})(\d{0,3})", ref)
    if not m:
        raise EkycError("BAD_FILE", "The e-KYC reference is missing.")
    generated = datetime.strptime(m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=TIMEZONE_IST)
    now = now or datetime.now(timezone.utc)
    if generated > now + timedelta(minutes=10):
        raise EkycError("BAD_FILE", "The e-KYC file has an invalid date.")
    if now - generated > timedelta(hours=max_age_hours):
        raise EkycError("TOO_OLD", f"This e-KYC file is older than {max_age_hours} hours. Please download a fresh one.")

    poi = root.find("UidData/Poi")
    if poi is None:
        raise EkycError("BAD_FILE", "The e-KYC file has no identity details.")
    gender = (poi.get("gender") or "").strip().upper()[:1]
    if gender not in ("M", "F", "T"):
        raise EkycError("BAD_FILE", "The e-KYC file has no gender.")
    photo_b64 = root.findtext("UidData/Pht")
    photo = base64.b64decode("".join(photo_b64.split())) if photo_b64 else None
    return EkycResult(name=" ".join((poi.get("name") or "").split()), date_of_birth=_parse_dob(poi.get("dob") or ""),
                      gender=gender, photo_jpeg=photo, generated_at=generated, last4=m.group(1))


def name_letters(name: str) -> str:
    return "".join(re.findall(r"[A-Za-z]", name or "")).upper()[:4]


def identity_fingerprint(secret: bytes, result: EkycResult) -> str:
    """Keyed hash (not reversible without the server key) used only to stop one Aadhaar on many accounts.
    Same inputs for the e-KYC ZIP and the e-Aadhaar PDF, so both routes map one Aadhaar to one fingerprint."""
    material = f"{result.last4}|{result.date_of_birth}|{result.name4}|{result.gender}".encode()
    return hmac.new(secret, material, hashlib.sha256).hexdigest()


def names_match(a: str, b: str) -> bool:
    norm = lambda s: set(re.findall(r"[a-z]+", s.lower()))  # noqa: E731
    na, nb = norm(a), norm(b)
    return bool(na and nb and (na <= nb or nb <= na or len(na & nb) >= 2))
