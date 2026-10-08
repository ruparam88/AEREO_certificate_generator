"""Tests for spreadsheet parser and sheet-based job creation.

Verifies:
- Parsing CSV recipient files with standard and alias column headers
- Parsing Excel (.xlsx) files
- Date formatting and normalization
- Endpoint POST /api/v1/recipients/parse-file
- Endpoint POST /api/v1/jobs/upload-sheet
- Rejection of invalid spreadsheets and missing required columns
"""

import io
import time
from openpyxl import Workbook
import pytest


def _create_sample_excel_bytes(rows: list[list]) -> bytes:
    """Helper to create an in-memory .xlsx file."""
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_csv_standard_headers(client):
    """CSV with standard headers (Name, Course, Date, Email) should parse cleanly."""
    csv_content = (
        "Name,Course,Date,Email\n"
        "Alice Johnson,Python Masterclass,2024-12-15,alice@example.com\n"
        "Bob Smith,Python Masterclass,2024-12-15,bob@example.com\n"
    ).encode("utf-8")

    response = client.post(
        "/api/v1/recipients/parse-file",
        files={"file": ("participants.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["name"] == "Alice Johnson"
    assert data[0]["course_name"] == "Python Masterclass"
    assert data[0]["date"] == "2024-12-15"
    assert data[0]["email"] == "alice@example.com"


def test_parse_csv_forgiving_header_aliases(client):
    """CSV with alias headers (Participant Name, Event, Completion Date) should map properly."""
    csv_content = (
        "Participant Name,Event,Completion Date,Email Address\n"
        "Diana Prince,Cloud Architecture,15/12/2024,diana@themyscira.com\n"
    ).encode("utf-8")

    response = client.post(
        "/api/v1/recipients/parse-file",
        files={"file": ("event_list.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Diana Prince"
    assert data[0]["course_name"] == "Cloud Architecture"
    assert data[0]["date"] == "2024-12-15"


def test_parse_excel_xlsx_file(client):
    """Excel .xlsx file should parse cells and dates correctly."""
    rows = [
        ["Full Name", "Workshop", "Date", "Email"],
        ["Bruce Wayne", "AI Ethics", "2024-11-20", "bruce@wayne.com"],
        ["Clark Kent", "AI Ethics", "2024-11-20", "clark@dailyplanet.com"],
    ]
    xlsx_bytes = _create_sample_excel_bytes(rows)

    response = client.post(
        "/api/v1/recipients/parse-file",
        files={"file": ("attendees.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["name"] == "Bruce Wayne"
    assert data[0]["course_name"] == "AI Ethics"
    assert data[0]["date"] == "2024-11-20"


def test_parse_missing_required_column_returns_400(client):
    """If a required column like Date is missing, return 400 with a helpful message."""
    csv_content = "Name,Course\nAlice,Python\n".encode("utf-8")
    response = client.post(
        "/api/v1/recipients/parse-file",
        files={"file": ("missing_date.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 400
    assert "Date" in response.json()["detail"]


def test_parse_unsupported_file_extension_returns_400(client):
    """Uploading an unsupported file format like .txt should return 400."""
    response = client.post(
        "/api/v1/recipients/parse-file",
        files={"file": ("data.txt", b"Hello World", "text/plain")},
    )
    assert response.status_code == 400
    assert "Unsupported" in response.json()["detail"]


def test_create_job_from_spreadsheet_endpoint(client):
    """POST /jobs/upload-sheet should parse the spreadsheet and kick off generation."""
    rows = [
        ["Name", "Course Name", "Date"],
        ["Sheet User 1", "FastAPI Mastery", "2024-12-15"],
        ["Sheet User 2", "FastAPI Mastery", "2024-12-15"],
    ]
    xlsx_bytes = _create_sample_excel_bytes(rows)

    response = client.post(
        "/api/v1/jobs/upload-sheet",
        data={"template_id": "classic"},
        files={"file": ("recipients.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 202
    job_data = response.json()
    assert job_data["total_recipients"] == 2
    assert job_data["status"] == "pending"

    # Wait for background task to complete
    time.sleep(0.5)

    # Check job completion
    status_res = client.get(f"/api/v1/jobs/{job_data['id']}")
    assert status_res.status_code == 200
    detail = status_res.json()
    assert detail["status"] == "completed"
    assert detail["successful_count"] == 2
    assert len(detail["certificates"]) == 2
