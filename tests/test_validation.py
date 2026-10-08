"""Tests for input validation.

Verifies that invalid recipient data is properly rejected with
meaningful error messages.
"""

import pytest


def test_missing_name_returns_422(client):
    """Name is required — omitting it should fail."""
    payload = {
        "recipients": [
            {
                "course_name": "Python 101",
                "date": "2024-01-01",
            }
        ]
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422


def test_empty_name_returns_422(client):
    """An empty name string should be rejected."""
    payload = {
        "recipients": [
            {
                "name": "",
                "course_name": "Python 101",
                "date": "2024-01-01",
            }
        ]
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422


def test_invalid_email_returns_422(client):
    """A malformed email should be rejected."""
    payload = {
        "recipients": [
            {
                "name": "Test User",
                "email": "not-an-email",
                "course_name": "Python 101",
                "date": "2024-01-01",
            }
        ]
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422


def test_invalid_date_format_returns_422(client):
    """Dates not in YYYY-MM-DD format should be rejected."""
    payload = {
        "recipients": [
            {
                "name": "Test User",
                "course_name": "Python 101",
                "date": "15/12/2024",
            }
        ]
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422


def test_impossible_date_returns_422(client):
    """A date that passes regex but isn't real (Feb 31) should fail."""
    payload = {
        "recipients": [
            {
                "name": "Test User",
                "course_name": "Python 101",
                "date": "2024-02-31",
            }
        ]
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422


def test_missing_course_name_returns_422(client):
    """Course name is required."""
    payload = {
        "recipients": [
            {
                "name": "Test User",
                "date": "2024-01-01",
            }
        ]
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422


def test_valid_data_without_email_accepted(client):
    """Email is optional — a request without it should succeed."""
    payload = {
        "recipients": [
            {
                "name": "Test User",
                "course_name": "Python 101",
                "date": "2024-01-01",
            }
        ]
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 202
