"""Local content-based media validation and deterministic metadata extraction."""

from __future__ import annotations

import hashlib
import re
import struct
import wave
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from typing import Any

from mediaos.application.errors import UploadValidationError
from mediaos.domain.enums import MediaType

ALLOWED_MIME_TYPES = {
    "image/jpeg": (MediaType.IMAGE, {".jpg", ".jpeg"}),
    "image/png": (MediaType.IMAGE, {".png"}),
    "image/webp": (MediaType.IMAGE, {".webp"}),
    "application/pdf": (MediaType.DOCUMENT, {".pdf"}),
    "audio/mpeg": (MediaType.AUDIO, {".mp3"}),
    "audio/wav": (MediaType.AUDIO, {".wav"}),
    "video/mp4": (MediaType.VIDEO, {".mp4"}),
}


@dataclass(frozen=True, slots=True)
class ValidatedMedia:
    content: bytes
    sha256: str
    claimed_mime_type: str | None
    detected_mime_type: str
    media_type: MediaType
    file_signature: str
    technical_metadata: dict[str, Any]
    quarantined: bool
    validation_issues: tuple[str, ...]


def validate_media(
    content: bytes,
    *,
    claimed_mime_type: str | None,
    original_filename: str | None,
    max_bytes: int,
) -> ValidatedMedia:
    if not content:
        raise UploadValidationError("Uploaded media file is empty")
    if len(content) > max_bytes:
        raise UploadValidationError(
            "Uploaded media exceeds the configured size limit", details={"max_bytes": max_bytes}
        )
    detected_mime, signature = _detect(content)
    if detected_mime not in ALLOWED_MIME_TYPES:
        raise UploadValidationError("Media signature is not an allowed file type")
    _ensure_complete_structure(content, detected_mime)
    media_type, expected_extensions = ALLOWED_MIME_TYPES[detected_mime]
    issues: list[str] = []
    normalized_claim = (claimed_mime_type or "").split(";", maxsplit=1)[0].strip().lower()
    if normalized_claim != detected_mime:
        issues.append("CLAIMED_MIME_MISMATCH")
    suffix = PurePath(original_filename or "").suffix.lower()
    if suffix and suffix not in expected_extensions:
        issues.append("FILE_EXTENSION_MISMATCH")
    metadata = extract_technical_metadata(content, detected_mime)
    return ValidatedMedia(
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        claimed_mime_type=normalized_claim or None,
        detected_mime_type=detected_mime,
        media_type=media_type,
        file_signature=signature,
        technical_metadata=metadata,
        quarantined=bool(issues),
        validation_issues=tuple(issues),
    )


def _detect(content: bytes) -> tuple[str, str]:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "JPEG_FFD8FF"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "PNG_89504E47"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp", "WEBP_RIFF"
    if re.match(rb"%PDF-\d\.\d", content[:8]):
        return "application/pdf", "PDF_HEADER"
    if content.startswith(b"ID3") or (
        len(content) >= 2 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg", "MP3_FRAME_OR_ID3"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WAVE":
        return "audio/wav", "WAV_RIFF"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        return "video/mp4", "MP4_FTYP"
    return "application/octet-stream", "UNKNOWN"


def _ensure_complete_structure(content: bytes, mime_type: str) -> None:
    if mime_type == "application/pdf" and b"%%EOF" not in content[-1024:]:
        raise UploadValidationError("PDF upload is incomplete")
    if mime_type == "video/mp4" and (b"moov" not in content or b"mdat" not in content):
        raise UploadValidationError("MP4 upload is incomplete")


def extract_technical_metadata(content: bytes, mime_type: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "file_size": len(content),
        "format": mime_type,
    }
    if mime_type == "image/png":
        if len(content) < 33 or content[12:16] != b"IHDR":
            raise UploadValidationError("PNG header is incomplete")
        width, height = struct.unpack(">II", content[16:24])
        color_type = content[25]
        metadata.update(
            {
                "width": width,
                "height": height,
                "color_space": _png_color_space(color_type),
                "transparent": color_type in {4, 6} or b"tRNS" in content,
                "orientation": "LANDSCAPE"
                if width > height
                else "PORTRAIT"
                if height > width
                else "SQUARE",
            }
        )
    elif mime_type == "image/jpeg":
        width, height = _jpeg_dimensions(content)
        metadata.update(
            {
                "width": width,
                "height": height,
                "color_space": "YCbCr",
                "transparent": False,
                "orientation": "LANDSCAPE"
                if width > height
                else "PORTRAIT"
                if height > width
                else "SQUARE",
            }
        )
    elif mime_type == "image/webp":
        width, height, transparent = _webp_dimensions(content)
        metadata.update(
            {
                "width": width,
                "height": height,
                "color_space": "RGB",
                "transparent": transparent,
                "orientation": "LANDSCAPE"
                if width > height
                else "PORTRAIT"
                if height > width
                else "SQUARE",
            }
        )
    elif mime_type == "application/pdf":
        version = content[5:8].decode("ascii", errors="replace")
        page_count = len(re.findall(rb"/Type\s*/Page(?!s)\b", content))
        metadata.update(
            {
                "pages": max(page_count, 1),
                "pdf_version": version,
                "encrypted": b"/Encrypt" in content,
            }
        )
    elif mime_type == "audio/wav":
        try:
            with wave.open(BytesIO(content), "rb") as audio:
                frames = audio.getnframes()
                rate = audio.getframerate()
                metadata.update(
                    {
                        "duration_seconds": round(frames / rate, 6) if rate else 0.0,
                        "codec": "PCM",
                        "sample_rate": rate,
                        "channels": audio.getnchannels(),
                        "bitrate": rate * audio.getnchannels() * audio.getsampwidth() * 8,
                    }
                )
        except (EOFError, wave.Error) as exc:
            raise UploadValidationError("WAV structure is invalid or incomplete") from exc
    elif mime_type == "audio/mpeg":
        metadata.update(_mp3_metadata(content))
    elif mime_type == "video/mp4":
        metadata.update(_mp4_metadata(content))
    return metadata


def _png_color_space(color_type: int) -> str:
    return {0: "GRAYSCALE", 2: "RGB", 3: "INDEXED", 4: "GRAYSCALE_ALPHA", 6: "RGBA"}.get(
        color_type, "UNKNOWN"
    )


def _jpeg_dimensions(content: bytes) -> tuple[int, int]:
    offset = 2
    while offset + 9 < len(content):
        if content[offset] != 0xFF:
            offset += 1
            continue
        marker = content[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(content):
            break
        length = int.from_bytes(content[offset : offset + 2], "big")
        if length < 2 or offset + length > len(content):
            break
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB}:
            height = int.from_bytes(content[offset + 3 : offset + 5], "big")
            width = int.from_bytes(content[offset + 5 : offset + 7], "big")
            if width and height:
                return width, height
        offset += length
    raise UploadValidationError("JPEG dimensions could not be verified")


def _webp_dimensions(content: bytes) -> tuple[int, int, bool]:
    chunk = content[12:16]
    if chunk == b"VP8X" and len(content) >= 30:
        flags = content[20]
        width = 1 + int.from_bytes(content[24:27], "little")
        height = 1 + int.from_bytes(content[27:30], "little")
        return width, height, bool(flags & 0x10)
    if chunk == b"VP8 " and len(content) >= 30 and content[23:26] == b"\x9d\x01\x2a":
        width = int.from_bytes(content[26:28], "little") & 0x3FFF
        height = int.from_bytes(content[28:30], "little") & 0x3FFF
        return width, height, False
    raise UploadValidationError("WebP dimensions could not be verified")


def _mp3_metadata(content: bytes) -> dict[str, Any]:
    offset = 10 if content.startswith(b"ID3") and len(content) >= 10 else 0
    while offset + 4 <= len(content):
        header = int.from_bytes(content[offset : offset + 4], "big")
        if header & 0xFFE00000 == 0xFFE00000:
            version_id = (header >> 19) & 0b11
            layer = (header >> 17) & 0b11
            bitrate_index = (header >> 12) & 0b1111
            sample_index = (header >> 10) & 0b11
            if (
                version_id == 3
                and layer == 1
                and bitrate_index not in {0, 15}
                and sample_index != 3
            ):
                bitrate = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320][
                    bitrate_index
                ]
                sample_rate = [44100, 48000, 32000][sample_index]
                channel_mode = (header >> 6) & 0b11
                return {
                    "codec": "MP3",
                    "sample_rate": sample_rate,
                    "channels": 1 if channel_mode == 3 else 2,
                    "bitrate": bitrate * 1000,
                    "duration_seconds": round(len(content) * 8 / (bitrate * 1000), 6),
                }
        offset += 1
    raise UploadValidationError("MP3 frame header could not be verified")


def _mp4_metadata(content: bytes) -> dict[str, Any]:
    major_brand = content[8:12].decode("ascii", errors="replace")
    metadata: dict[str, Any] = {
        "container": "MP4",
        "major_brand": major_brand,
        "codec": "UNKNOWN",
        "audio_present": b"soun" in content,
    }
    mvhd = content.find(b"mvhd")
    if mvhd >= 0 and mvhd + 24 <= len(content):
        version = content[mvhd + 4]
        base = mvhd + (24 if version == 1 else 16)
        if base + (12 if version == 1 else 8) <= len(content):
            timescale = int.from_bytes(content[base : base + 4], "big")
            duration_size = 8 if version == 1 else 4
            duration = int.from_bytes(content[base + 4 : base + 4 + duration_size], "big")
            if timescale:
                metadata["duration_seconds"] = round(duration / timescale, 6)
    codec_markers = {
        b"avc1": "H.264/AVC",
        b"avc3": "H.264/AVC",
        b"hvc1": "H.265/HEVC",
        b"hev1": "H.265/HEVC",
        b"vp09": "VP9",
        b"av01": "AV1",
    }
    metadata["codec"] = next(
        (codec for marker, codec in codec_markers.items() if marker in content), "UNKNOWN"
    )
    for payload in _mp4_box_payloads(content, b"tkhd"):
        if len(payload) < 8:
            continue
        width = int.from_bytes(payload[-8:-4], "big") >> 16
        height = int.from_bytes(payload[-4:], "big") >> 16
        if width and height:
            metadata["width"] = width
            metadata["height"] = height
            break
    return metadata


def _mp4_box_payloads(content: bytes, box_type: bytes) -> list[bytes]:
    payloads: list[bytes] = []
    offset = 0
    while True:
        marker = content.find(box_type, offset)
        if marker < 4:
            return payloads
        start = marker - 4
        size = int.from_bytes(content[start:marker], "big")
        end = start + size
        if size >= 8 and end <= len(content):
            payloads.append(content[marker + 4 : end])
        offset = marker + 4
