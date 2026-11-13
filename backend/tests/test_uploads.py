"""Upload validation. Regression tests for audit findings C4, C5 and S12."""
import struct
import zlib
import numpy as np
from tests.conftest import encode, road_image


def post(client, content: bytes, name: str = "road.jpg", content_type: str = "image/jpeg"):
    return client.post("/detect", files={"file": (name, content, content_type)})


def test_empty_file_is_rejected_not_a_server_error(client):
    response = post(client, b"")
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_non_image_content_is_rejected_even_with_image_content_type(client):
    assert post(client, b"this is not an image").status_code == 415


def test_file_type_comes_from_content_not_headers_or_name(client, road_jpeg):
    response = post(client, road_jpeg, name="notes.txt", content_type="application/octet-stream")
    assert response.status_code == 200


def test_truncated_jpeg_is_rejected(client, road_jpeg):
    response = post(client, road_jpeg[:40])
    assert response.status_code == 400
    assert "could not be decoded" in response.json()["detail"]


def test_garbage_after_valid_signature_is_rejected(client):
    assert post(client, b"\x89PNG\r\n\x1a\n" + b"\x00" * 200, "x.png", "image/png").status_code == 400


def test_png_and_webp_are_accepted(client):
    assert post(client, encode(road_image(), ".png"), "road.png", "image/png").status_code == 200
    assert post(client, encode(road_image(), ".webp"), "road.webp", "image/webp").status_code == 200


def test_tiny_image_is_rejected(client):
    assert post(client, encode(np.zeros((8, 8, 3), np.uint8), ".png"), "x.png").status_code == 400


def test_file_over_the_size_limit_is_rejected(client):
    # Limit is 2 MB in tests; random noise does not compress.
    noise = np.random.default_rng(0).integers(0, 255, (850, 850, 3), dtype=np.uint8)
    content = encode(noise, ".png")
    assert 2 * 1024 * 1024 < len(content) < 3 * 1024 * 1024
    response = post(client, content, "big.png", "image/png")
    assert response.status_code == 413
    assert "2 MB" in response.json()["detail"]


def test_declared_oversized_body_is_refused_before_processing(client):
    response = client.post("/detect", content=b"x" * (4 * 1024 * 1024), headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert response.status_code == 413


def test_streamed_oversized_body_without_length_is_refused(client):
    def chunks():
        yield b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
        for _ in range(40):
            yield b"\xff" * (100 * 1024)
        yield b"\r\n--x--\r\n"
    response = client.post("/detect", content=chunks(), headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert response.status_code == 413


def png_claiming_size(width: int, height: int) -> bytes:
    """A small, valid PNG whose header declares huge dimensions (decompression bomb)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    rows = zlib.compress(b"\x00" * ((width + 1) * height), 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", rows) + chunk(b"IEND", b"")


def test_decompression_bomb_is_rejected(client):
    bomb = png_claiming_size(6000, 6000)  # 36 MP against an 8 MP test limit, in a few KB
    assert len(bomb) < 100_000
    response = post(client, bomb, "bomb.png", "image/png")
    assert response.status_code == 413
    assert "megapixels" in response.json()["detail"]


def test_declared_size_is_read_for_every_accepted_format():
    from app.services.images import read_declared_size
    image = road_image()[:300, :500]
    for extension, name in ((".jpg", "jpeg"), (".png", "png"), (".webp", "webp")):
        assert read_declared_size(encode(image, extension), name) == (500, 300), name
    import cv2
    lossless = cv2.imencode(".webp", image, [cv2.IMWRITE_WEBP_QUALITY, 101])[1].tobytes()
    assert read_declared_size(lossless, "webp") == (500, 300)
    assert read_declared_size(b"\xff\xd8\xff\xe0", "jpeg") is None


def test_missing_file_field_is_a_validation_error(client):
    assert client.post("/detect").status_code == 422


def test_rejected_uploads_leave_nothing_behind(client):
    post(client, b"")
    post(client, b"nope")
    assert client.get("/inspections").json() == []
