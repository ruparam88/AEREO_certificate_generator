"""Tests for certificate failure handling.

Verifies that the system handles individual certificate failures
gracefully without blocking other certificates in the same job.
"""

import time
from unittest.mock import patch


def test_one_failure_does_not_block_others(client):
    """If one certificate fails, others should still succeed.

    We mock the generator to fail on the second recipient only.
    """
    payload = {
        "recipients": [
            {"name": "Alice", "course_name": "Course A", "date": "2024-01-01"},
            {"name": "Bob", "course_name": "Course A", "date": "2024-01-01"},
            {"name": "Charlie", "course_name": "Course A", "date": "2024-01-01"},
        ]
    }

    call_count = 0
    original_generate = None

    def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("Simulated generation failure")
        # Import here to avoid circular
        from app.services.certificate_generator import generate_certificate as real_gen
        return real_gen(*args, **kwargs)

    with patch(
        "app.services.job_service.generate_certificate",
        side_effect=mock_generate,
    ):
        response = client.post("/api/v1/jobs", json=payload)
        job_id = response.json()["id"]
        time.sleep(0.5)

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    assert status["successful_count"] == 2
    assert status["failed_count"] == 1
    assert status["status"] == "completed"


def test_failed_certificate_has_error_message(client):
    """A failed certificate should have a populated error_message."""
    payload = {
        "recipients": [
            {"name": "Fail User", "course_name": "Course", "date": "2024-01-01"},
        ]
    }

    with patch(
        "app.services.job_service.generate_certificate",
        side_effect=RuntimeError("Test error message"),
    ):
        response = client.post("/api/v1/jobs", json=payload)
        job_id = response.json()["id"]
        time.sleep(0.5)

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    failed_certs = [c for c in status["certificates"] if c["status"] == "failed"]
    assert len(failed_certs) == 1
    assert "Test error message" in failed_certs[0]["error_message"]


def test_all_failures_still_completes_job(client):
    """Even if every certificate fails, the job should complete."""
    payload = {
        "recipients": [
            {"name": "User 1", "course_name": "Course", "date": "2024-01-01"},
            {"name": "User 2", "course_name": "Course", "date": "2024-01-01"},
        ]
    }

    with patch(
        "app.services.job_service.generate_certificate",
        side_effect=RuntimeError("All fail"),
    ):
        response = client.post("/api/v1/jobs", json=payload)
        job_id = response.json()["id"]
        time.sleep(0.5)

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    assert status["status"] == "completed"
    assert status["failed_count"] == 2
    assert status["successful_count"] == 0
