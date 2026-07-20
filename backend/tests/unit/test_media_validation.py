"""Content-signature and local metadata extraction tests for Hauptblock 6."""

import struct
import wave
from io import BytesIO

import pytest

from mediaos.application.errors import UploadValidationError
from mediaos.application.media_validation import validate_media
from mediaos.domain.enums import MediaType


def png(width: int = 3, height: int = 2) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + struct.pack(">II", width, height)
        + bytes([8, 6, 0, 0, 0])
        + b"payload"
    )


def jpeg(width: int = 3, height: int = 2) -> bytes:
    sof = b"\xff\xc0\x00\x11\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big")
    return b"\xff\xd8" + sof + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"


def webp(width: int = 3, height: int = 2) -> bytes:
    body = (
        b"WEBPVP8X"
        + b"\x00\x00\x00\x00"
        + b"\x10\x00\x00\x00"
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def wav() -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 80)
    return output.getvalue()


def test_image_signatures_and_metadata() -> None:
    cases = [
        (png(), "image/png", "image.png"),
        (jpeg(), "image/jpeg", "image.jpg"),
        (webp(), "image/webp", "image.webp"),
    ]
    for content, mime_type, filename in cases:
        result = validate_media(
            content,
            claimed_mime_type=mime_type,
            original_filename=filename,
            max_bytes=10000,
        )
        assert result.media_type == MediaType.IMAGE
        assert result.detected_mime_type == mime_type
        assert result.technical_metadata["width"] == 3
        assert result.technical_metadata["height"] == 2
        assert result.quarantined is False


def test_pdf_audio_and_video_metadata() -> None:
    pdf = validate_media(
        b"%PDF-1.7\n1 0 obj<</Type /Page>>endobj\n%%EOF",
        claimed_mime_type="application/pdf",
        original_filename="proof.pdf",
        max_bytes=10000,
    )
    assert pdf.media_type == MediaType.DOCUMENT
    assert pdf.technical_metadata == {
        "file_size": 43,
        "format": "application/pdf",
        "pages": 1,
        "pdf_version": "1.7",
        "encrypted": False,
    }
    audio = validate_media(
        wav(), claimed_mime_type="audio/wav", original_filename="audio.wav", max_bytes=10000
    )
    assert audio.technical_metadata["sample_rate"] == 8000
    assert audio.technical_metadata["channels"] == 1
    mp3 = validate_media(
        b"\xff\xfb\x90\x64" + b"\x00" * 1000,
        claimed_mime_type="audio/mpeg",
        original_filename="audio.mp3",
        max_bytes=10000,
    )
    assert mp3.technical_metadata["codec"] == "MP3"
    mp4_content = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
    video = validate_media(
        mp4_content,
        claimed_mime_type="video/mp4",
        original_filename="video.mp4",
        max_bytes=10000,
    )
    assert video.media_type == MediaType.VIDEO
    assert video.technical_metadata["container"] == "MP4"


def test_empty_size_unknown_and_invalid_structures_are_blocked() -> None:
    with pytest.raises(UploadValidationError, match="empty"):
        validate_media(b"", claimed_mime_type="image/png", original_filename="x.png", max_bytes=1)
    with pytest.raises(UploadValidationError, match="size limit"):
        validate_media(png(), claimed_mime_type="image/png", original_filename="x.png", max_bytes=4)
    with pytest.raises(UploadValidationError, match="allowed file type"):
        validate_media(
            b"<html>active</html>",
            claimed_mime_type="text/html",
            original_filename="x.html",
            max_bytes=100,
        )
    with pytest.raises(UploadValidationError, match="incomplete"):
        validate_media(
            b"\x89PNG\r\n\x1a\n",
            claimed_mime_type="image/png",
            original_filename="x.png",
            max_bytes=100,
        )


def test_claimed_mime_and_extension_mismatch_are_quarantined() -> None:
    result = validate_media(
        png(),
        claimed_mime_type="application/pdf",
        original_filename="misleading.pdf",
        max_bytes=10000,
    )
    assert result.detected_mime_type == "image/png"
    assert result.quarantined is True
    assert set(result.validation_issues) == {
        "CLAIMED_MIME_MISMATCH",
        "FILE_EXTENSION_MISMATCH",
    }
