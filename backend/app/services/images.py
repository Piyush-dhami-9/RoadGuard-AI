"""Upload validation, decoding and on-disk storage of inspection images."""
import logging
import struct
import uuid
from pathlib import Path
import cv2
import numpy as np
from ..core.config import settings

logger = logging.getLogger(__name__)
MIN_IMAGE_SIDE = 32
ACCEPTED_FORMATS = "JPEG, PNG or WebP"


class UploadRejected(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def sniff_image_format(content: bytes) -> str | None:
    """Identify the format from the file's leading bytes, never from client-supplied metadata."""
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    return None


def read_declared_size(content: bytes, image_format: str) -> tuple[int, int] | None:
    """Width and height as declared in the file header, read without decoding any pixels.

    Decoders allocate memory from these values, so checking them first stops a
    small file that declares enormous dimensions (a decompression bomb).
    """
    try:
        if image_format == "png":
            if content[12:16] != b"IHDR":
                return None
            return struct.unpack(">II", content[16:24])
        if image_format == "webp":
            kind = content[12:16]
            if kind == b"VP8X":
                return int.from_bytes(content[24:27], "little") + 1, int.from_bytes(content[27:30], "little") + 1
            if kind == b"VP8L":
                bits = int.from_bytes(content[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            if kind == b"VP8 ":
                width, height = struct.unpack("<HH", content[26:30])
                return width & 0x3FFF, height & 0x3FFF
            return None
        position = 2  # JPEG: walk the segments to the first start-of-frame marker
        while position + 9 <= len(content):
            if content[position] != 0xFF:
                return None
            marker = content[position + 1]
            if marker == 0xFF:
                position += 1
                continue
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", content[position + 5:position + 9])
                return width, height
            position += 2 + int.from_bytes(content[position + 2:position + 4], "big")
        return None
    except struct.error:
        return None


def decode_upload(content: bytes) -> np.ndarray:
    if not content:
        raise UploadRejected(400, "The uploaded file is empty")
    if len(content) > settings.max_upload_bytes:
        raise UploadRejected(413, f"The image exceeds the {settings.max_upload_mb} MB upload limit")
    image_format = sniff_image_format(content)
    if image_format is None:
        raise UploadRejected(415, f"Unsupported file type. Upload a {ACCEPTED_FORMATS} image")
    undecodable = UploadRejected(400, "The image is corrupt and could not be decoded")
    declared = read_declared_size(content, image_format)
    if declared is None or min(declared) < 1:
        raise undecodable
    if declared[0] * declared[1] > settings.max_image_megapixels * 1_000_000:
        raise UploadRejected(413, f"The image is {declared[0]}x{declared[1]} px; the limit is {settings.max_image_megapixels} megapixels")
    try:
        image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as error:
        raise undecodable from error
    if image is None:
        raise undecodable
    height, width = image.shape[:2]
    if min(height, width) < MIN_IMAGE_SIDE:
        raise UploadRejected(400, f"The image is too small to inspect (minimum {MIN_IMAGE_SIDE} px per side)")
    return image


def save_inspection_images(original: np.ndarray, annotated: np.ndarray) -> tuple[Path, Path]:
    """Write both images under server-generated names; nothing is left behind on failure."""
    name = f"{uuid.uuid4().hex}.jpg"
    original_path = settings.upload_dir / name
    annotated_path = settings.upload_dir / f"annotated-{name}"
    try:
        for path, image in ((original_path, original), (annotated_path, annotated)):
            if not cv2.imwrite(str(path), image):
                raise OSError(f"Could not write {path}")
    except Exception:
        remove_files(original_path, annotated_path)
        raise
    return original_path, annotated_path


def stored_file(stored_path: str | None) -> Path | None:
    """Resolve a path recorded in the database to a file inside the upload directory.

    Only the file name is trusted, so a tampered or legacy value can never
    point outside the upload directory.
    """
    if not stored_path:
        return None
    candidate = settings.upload_dir / Path(stored_path).name
    return candidate if candidate.is_file() else None


def remove_files(*paths: Path | None) -> None:
    for path in paths:
        if path is None:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove %s", path, exc_info=True)
