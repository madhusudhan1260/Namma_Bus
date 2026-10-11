"""
Face verification adapters.

BiometricProvider
  ├── MockBiometricProvider        BIOMETRIC_PROVIDER=mock (development only). It performs NO face
  │                                recognition: the outcome is chosen by the developer and labelled.
  ├── OpenCVFaceProvider           BIOMETRIC_PROVIDER=opencv. Real 1:1 face matching on this server: OpenCV
  │                                YuNet finds the face, SFace compares it with the reference photo (the photo
  │                                inside the passenger's UIDAI-signed Offline e-KYC). It is NOT certified
  │                                liveness detection, so a printed photo held up to the camera may pass.
  └── UnavailableBiometricProvider BIOMETRIC_PROVIDER=unavailable

The capture and the reference are processed in memory only; no image, embedding or template from the live
capture is stored. Only the result, the similarity score and an opaque reference are kept (FaceVerificationAttempt).
"""

import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import settings

DEV_LABEL = "DEVELOPMENT VERIFICATION — NOT REAL IDENTITY VERIFICATION"


@dataclass
class BiometricResult:
    result: str  # MATCH | NO_MATCH | UNAVAILABLE | ERROR
    reference: Optional[str] = None
    detail: str = ""
    score: Optional[float] = None


def looks_like_image(data: bytes) -> bool:
    return data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n")


class BiometricProvider(ABC):
    name = "BASE"
    is_development = False
    needs_reference_image = False

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def verify(self, capture: bytes, identity_reference: str, mock_outcome: Optional[str] = None,
               reference_image: Optional[bytes] = None) -> BiometricResult: ...


class MockBiometricProvider(BiometricProvider):
    name = "MOCK_DEVELOPMENT"
    is_development = True

    def available(self) -> bool:
        return True

    def verify(self, capture: bytes, identity_reference: str, mock_outcome: Optional[str] = None,
               reference_image: Optional[bytes] = None) -> BiometricResult:
        # A camera capture is still required so the flow matches production; its content is not analysed.
        if not looks_like_image(capture):
            return BiometricResult(result="ERROR", detail="A camera image (JPEG/PNG) is required.")
        if mock_outcome == "MATCH":
            return BiometricResult(result="MATCH", reference=f"MOCKFACE-{secrets.token_hex(6).upper()}", detail=DEV_LABEL)
        return BiometricResult(result="NO_MATCH", reference=f"MOCKFACE-{secrets.token_hex(6).upper()}", detail=DEV_LABEL)


class UnavailableBiometricProvider(BiometricProvider):
    name = "UNAVAILABLE"

    def available(self) -> bool:
        return False

    def verify(self, capture: bytes, identity_reference: str, mock_outcome: Optional[str] = None,
               reference_image: Optional[bytes] = None) -> BiometricResult:
        return BiometricResult(result="UNAVAILABLE", detail="Face verification is temporarily unavailable.")


YUNET_MODEL = "face_detection_yunet_2023mar.onnx"
SFACE_MODEL = "face_recognition_sface_2021dec.onnx"


class OpenCVFaceProvider(BiometricProvider):
    """1:1 face verification with OpenCV's YuNet detector and SFace recognizer (cosine similarity)."""

    name = "OPENCV_SFACE"
    needs_reference_image = True

    def __init__(self, model_dir: Optional[str] = None, threshold: Optional[float] = None):
        self.model_dir = Path(model_dir or settings.face_model_dir)
        self.threshold = settings.face_match_threshold if threshold is None else threshold

    def available(self) -> bool:
        try:
            import cv2  # noqa: F401
        except ImportError:
            return False
        return (self.model_dir / YUNET_MODEL).is_file() and (self.model_dir / SFACE_MODEL).is_file()

    def _decode(self, data: bytes):
        import cv2
        import numpy as np

        img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
        h, w = img.shape[:2]
        if max(h, w) > 1280:  # keep detection fast and memory bounded
            scale = 1280 / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))
        return img

    def count_faces(self, image: bytes) -> list:
        """Face boxes found in an image (used to locate the holder's photo inside an e-Aadhaar PDF)."""
        import cv2

        img = self._decode(image)
        if img is None:
            return []
        detector = cv2.FaceDetectorYN.create(str(self.model_dir / YUNET_MODEL), "", (320, 320), 0.8, 0.3, 5000)
        return [list(f[:4]) for f in self._faces(detector, img)]

    def _faces(self, detector, img):
        detector.setInputSize((img.shape[1], img.shape[0]))
        _, faces = detector.detect(img)
        return [] if faces is None else list(faces)

    def verify(self, capture: bytes, identity_reference: str, mock_outcome: Optional[str] = None,
               reference_image: Optional[bytes] = None) -> BiometricResult:
        import cv2

        if not reference_image:
            return BiometricResult(result="ERROR", detail="No reference photo is on file. Verify your Aadhaar e-KYC again.")
        if not looks_like_image(capture):
            return BiometricResult(result="ERROR", detail="A camera image (JPEG/PNG) is required.")
        live, ref = self._decode(capture), self._decode(reference_image)
        if live is None or ref is None:
            return BiometricResult(result="ERROR", detail="The image could not be read.")
        detector = cv2.FaceDetectorYN.create(str(self.model_dir / YUNET_MODEL), "", (320, 320), 0.8, 0.3, 5000)
        recognizer = cv2.FaceRecognizerSF.create(str(self.model_dir / SFACE_MODEL), "")
        live_faces, ref_faces = self._faces(detector, live), self._faces(detector, ref)
        if not live_faces:
            return BiometricResult(result="ERROR", detail="No face found. Face the camera in good light and try again.")
        if len(live_faces) > 1:
            return BiometricResult(result="ERROR", detail="More than one face is in the picture. Only you should be in view.")
        if not ref_faces:
            return BiometricResult(result="ERROR", detail="The reference photo could not be used for matching.")
        ref_face = max(ref_faces, key=lambda f: f[2] * f[3])
        f_live = recognizer.feature(recognizer.alignCrop(live, live_faces[0]))
        f_ref = recognizer.feature(recognizer.alignCrop(ref, ref_face))
        score = float(recognizer.match(f_live, f_ref, cv2.FaceRecognizerSF_FR_COSINE))
        result = "MATCH" if score >= self.threshold else "NO_MATCH"
        return BiometricResult(result=result, reference=f"FACE-{secrets.token_hex(6).upper()}", score=round(score, 3),
                               detail=f"similarity {score:.3f} (threshold {self.threshold:.3f})")


_override: Optional[BiometricProvider] = None


def get_biometric_provider() -> BiometricProvider:
    if _override is not None:
        return _override
    if settings.biometric_provider == "mock":
        return MockBiometricProvider()
    if settings.biometric_provider == "opencv":
        return OpenCVFaceProvider()
    return UnavailableBiometricProvider()


def set_biometric_provider(provider: Optional[BiometricProvider]) -> None:
    global _override
    _override = provider
