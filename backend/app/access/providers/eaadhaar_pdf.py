"""
UIDAI e-Aadhaar PDF verification (the PDF from "Download Aadhaar" on myaadhaar.uidai.gov.in, full or masked).

The PDF is password-protected (first 4 letters of the name in CAPITALS + year of birth, e.g. ASHA1995) and digitally
signed by UIDAI. This module:

  1. finds the PDF signature and requires it to cover the WHOLE file (nothing appended after signing),
  2. verifies the CMS signature over the signed bytes and builds the signer's certificate chain to a trusted root
     certificate in ACCESS_TRUSTED_CA_DIR (e.g. CCA India), and requires the signer to be UIDAI,
  3. opens the PDF with the passenger's password (which itself proves the first 4 letters of the name and the
     year of birth), and reads only gender, date of birth, the last 4 digits (transient) and the photo.

The Aadhaar number, address and the PDF itself are never stored. Without trusted root certificates nothing is
marked VERIFIED.
"""

import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from cryptography import x509

from .aadhaar_ekyc import EkycError, EkycResult, _parse_dob
from .cms import CmsError, verify_detached

UIDAI_ORG = "UNIQUE IDENTIFICATION AUTHORITY OF INDIA"
BYTERANGE = re.compile(rb"/ByteRange\s*\[\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*\]")


def load_anchors(directory: str) -> List[x509.Certificate]:
    anchors = []
    path = Path(directory) if directory else None
    if not path or not path.is_dir():
        return anchors
    for f in sorted(path.iterdir()):
        if f.suffix.lower() not in (".cer", ".crt", ".pem", ".der"):
            continue
        data = f.read_bytes()
        for loader in (x509.load_pem_x509_certificates, lambda d: [x509.load_der_x509_certificate(d)]):
            try:
                anchors.extend(loader(data))
                break
            except ValueError:
                continue
    return anchors


def _signature(pdf: bytes):
    ranges = [tuple(int(x) for x in m.groups()) for m in BYTERANGE.finditer(pdf)]
    if not ranges:
        raise EkycError("NOT_SIGNED", "This PDF has no digital signature. Download e-Aadhaar again from the UIDAI website.")
    a, b, c, d = max(ranges, key=lambda r: r[2] + r[3])
    if a != 0 or c + d != len(pdf) or b > c:
        raise EkycError("BAD_SIGNATURE", "The PDF was changed after UIDAI signed it.")
    gap = pdf[b:c].strip()
    if not (gap.startswith(b"<") and gap.endswith(b">")):
        raise EkycError("BAD_SIGNATURE", "The PDF signature could not be read.")
    try:
        cms = bytes.fromhex(gap[1:-1].decode("ascii"))
    except ValueError:
        raise EkycError("BAD_SIGNATURE", "The PDF signature could not be read.")
    return pdf[a : a + b] + pdf[c : c + d], cms


def _text_and_images(pdf: bytes, password: str):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(pdf))
        if reader.is_encrypted and not reader.decrypt(password):
            raise EkycError("BAD_PASSWORD", "The PDF password is incorrect. It is the first 4 letters of your name in CAPITALS + your birth year, e.g. ASHA1995.")
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:4])
        images = []
        for page in reader.pages[:4]:
            for img in page.images:
                try:
                    pil = img.image.convert("RGB")
                except Exception:
                    continue
                if min(pil.size) < 60:
                    continue
                buf = io.BytesIO()
                pil.save(buf, "JPEG", quality=92)
                images.append((pil.size, buf.getvalue()))
        return text, images
    except EkycError:
        raise
    except (PdfReadError, ValueError, KeyError, NotImplementedError):
        raise EkycError("BAD_FILE", "The PDF could not be opened. Upload the e-Aadhaar PDF downloaded from the UIDAI website.")


def _pick_photo(images) -> Optional[bytes]:
    """The holder's photo is the embedded image with exactly one face (the QR code and logos have none)."""
    from .biometric import OpenCVFaceProvider

    finder = OpenCVFaceProvider()
    if finder.available():
        scored = []
        for (w, h), jpeg in images:
            faces = finder.count_faces(jpeg)
            if len(faces) == 1:
                scored.append((faces[0][2] * faces[0][3], jpeg))
        return max(scored)[1] if scored else None
    portrait = [(w * h, jpeg) for (w, h), jpeg in images if h > w * 1.05]
    return max(portrait)[1] if portrait else None


def _gender(text: str) -> Optional[str]:
    if re.search(r"\bFEMALE\b", text, re.I) or "महिला" in text:
        return "F"
    if re.search(r"\bTRANSGENDER\b", text, re.I):
        return "T"
    if re.search(r"\bMALE\b", text, re.I) or "पुरुष" in text:
        return "M"
    return None


def _last4(text: str) -> Optional[str]:
    # Aadhaar (or masked) number: "1234 5678 9012" / "XXXX XXXX 9012"; never a 16-digit VID
    m = re.search(r"(?<![\dXx] )(?<![\dXx])(?:\d{4}|[Xx]{4})\s(?:\d{4}|[Xx]{4})\s(\d{4})(?!\s?\d)", text)
    return m.group(1) if m else None


def verify_eaadhaar_pdf(pdf: bytes, password: str, trusted_dir: str, now: Optional[datetime] = None,
                        pinned_cert_path: Optional[str] = None) -> EkycResult:
    """Trust = a chain to a root in `trusted_dir`, or a signer key equal to UIDAI's published certificate."""
    anchors = load_anchors(trusted_dir)
    pinned = []
    if pinned_cert_path and Path(pinned_cert_path).is_file():
        from .aadhaar_ekyc import load_certificate

        pinned = [load_certificate(pinned_cert_path)]
    if not anchors and not pinned:
        raise EkycError("UNAVAILABLE", "e-Aadhaar PDF verification is not configured on this server yet.")
    if not pdf.startswith(b"%PDF"):
        raise EkycError("BAD_FILE", "Upload the e-Aadhaar PDF downloaded from the UIDAI website.")
    pw = (password or "").strip().upper()
    m = re.fullmatch(r"([A-Z]{1,4})(\d{4})", pw)
    if not m:
        raise EkycError("BAD_PASSWORD", "The PDF password is the first 4 letters of your name in CAPITALS + your birth year, e.g. ASHA1995.")

    signed_bytes, cms = _signature(pdf)
    try:
        info = verify_detached(cms, signed_bytes, anchors, now=now, pinned=pinned)
    except CmsError as e:
        raise EkycError("BAD_SIGNATURE", str(e))
    orgs = [a.value for a in info.signer.subject.get_attributes_for_oid(x509.NameOID.ORGANIZATION_NAME)]
    if not any(UIDAI_ORG in o.upper() for o in orgs):
        raise EkycError("BAD_SIGNATURE", "This PDF is not signed by UIDAI.")

    text, images = _text_and_images(pdf, pw)
    dob = None
    dm = re.search(r"(?:DOB|Date of Birth)\s*[:：]?\s*(\d{2}[/-]\d{2}[/-]\d{4})", text, re.I)
    if dm:
        dob = _parse_dob(dm.group(1).replace("/", "-"))
    yob = int(m.group(2))
    if dob and dob.year != yob:
        raise EkycError("BAD_FILE", "The date of birth in the PDF does not match its password.")
    gender = _gender(text)
    if not gender:
        raise EkycError("BAD_FILE", "Gender could not be read from this e-Aadhaar PDF.")
    photo = _pick_photo(images)
    return EkycResult(name="", date_of_birth=dob, gender=gender, photo_jpeg=photo,
                      generated_at=info.signing_time or now or datetime.now(timezone.utc),
                      last4=_last4(text) or "", name4=m.group(1))
