"""
Malware scanning hook for uploaded documents.

Default scanner: detects the standard EICAR test signature (to prove the hook blocks infected files) and
otherwise reports NOT_SCANNED — it never claims a file is clean. Plug a real engine (e.g. ClamAV) in by
implementing `DocumentScanner` and calling `set_scanner`, which can then return CLEAN.
"""

from abc import ABC, abstractmethod
from typing import Optional

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class DocumentScanner(ABC):
    @abstractmethod
    def scan(self, data: bytes) -> str:
        """Return CLEAN | INFECTED | NOT_SCANNED."""


class SignatureOnlyScanner(DocumentScanner):
    def scan(self, data: bytes) -> str:
        return "INFECTED" if EICAR in data else "NOT_SCANNED"


_scanner: Optional[DocumentScanner] = None


def get_scanner() -> DocumentScanner:
    return _scanner or SignatureOnlyScanner()


def set_scanner(scanner: Optional[DocumentScanner]) -> None:
    global _scanner
    _scanner = scanner
