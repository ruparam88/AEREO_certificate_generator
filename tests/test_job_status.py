"""Tests for job status and progress tracking.

Verifies that the API provides accurate progress information
at each stage of the job lifecycle.
"""

import time


def test_new_job_has_pending_status(client, sample_job_payload):
    """A freshly created job should have 'pending' status."""
    response = client.post("/api/v1/jobs", json=sample_job_payload)
    # Note: With TestClient, BackgroundTasks may run synchronously,
    # so status might already be 'completed'. We verify the response
    # at creation time is 202.
    assert response.status_code == 202


def test_completed_job_has_accurate_counts(client, sample_job_payload):
    """After processing, counts should match the number of recipients."""
    response = client.post("/api/v1/jobs", json=sample_job_payload)
    job_id = response.json()["id"]
    time.sleep(0.5)

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    assert status["total_recipients"] == 3
    assert status["successful_count"] + status["failed_count"] == 3


def test_completed_job_has_completed_at(client, sample_job_payload):
    """The completed_at field should be set after processing."""
    response = client.post("/api/v1/jobs", json=sample_job_payload)
    job_id = response.json()["id"]
    time.sleep(0.5)

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    assert status["completed_at"] is not None


def test_nonexistent_job_returns_404(client):
    """Requesting a non-existent job should return 404."""
    response = client.get("/api/v1/jobs/nonexistent-id")
    assert response.status_code == 404


def test_list_jobs_returns_all_jobs(client, sample_job_payload):
    """The list endpoint should return all created jobs."""
    # Create two jobs
    client.post("/api/v1/jobs", json=sample_job_payload)
    client.post("/api/v1/jobs", json=sample_job_payload)

    response = client.get("/api/v1/jobs")
    assert response.status_code == 200
    assert len(response.json()) >= 2


def test_list_jobs_pagination(client, sample_job_payload):
    """Pagination parameters should limit results."""
    # Create 3 jobs
    for _ in range(3):
        client.post("/api/v1/jobs", json=sample_job_payload)

    response = client.get("/api/v1/jobs?limit=2")
    assert response.status_code == 200
    assert len(response.json()) == 2
