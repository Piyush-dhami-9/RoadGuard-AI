"""PDF generation. Regression for C2 (the UI's GET request used to return 405)."""
import base64
import sqlite3
import zlib
import re
import pytest
from tests.conftest import DB_FILE, WORKDIR


def pdf_text(pdf: bytes) -> str:
    """Visible text of the report: decode the page streams and join the drawn strings."""
    text = []
    for stream in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            page = zlib.decompress(base64.a85decode(b"<~" + stream.strip(), adobe=True))  # ReportLab omits the leading <~
        except Exception:
            continue
        text += re.findall(r"\((.*?)\) Tj", page.decode("latin-1"))
    return " ".join(text)


@pytest.mark.parametrize("method", ["get", "post"])
def test_report_downloads_with_get_and_post(client, uploaded, method):
    response = getattr(client, method)(f"/report/{uploaded['id']}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert f"roadguard-inspection-{uploaded['id']}.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-") and len(response.content) > 5000


def test_report_for_missing_inspection_is_404(client):
    assert client.get("/report/999999").status_code == 404


def test_demo_report_states_demo_mode_and_disclaimer(client, uploaded):
    text = pdf_text(client.get(f"/report/{uploaded['id']}").content)
    assert "DEMO MODE" in text and "NOT AI predictions" in text
    assert "not a certified engineering assessment" in text
    assert "TRAINED MODEL" not in text


def test_report_survives_missing_image_and_no_damages(client, uploaded):
    for path in (WORKDIR / "uploads").glob("*"):
        path.unlink()
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute("DELETE FROM damages WHERE inspection_id = ?", (uploaded["id"],))
        connection.execute("UPDATE inspections SET annotated_image_path = NULL WHERE id = ?", (uploaded["id"],))
    response = client.get(f"/report/{uploaded['id']}")
    assert response.status_code == 200
    text = pdf_text(response.content)
    assert "no longer available" in text and "No damage regions" in text


def test_report_writes_no_files_to_disk(client, uploaded, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client.get(f"/report/{uploaded['id']}")
    assert list(tmp_path.rglob("*.pdf")) == []
