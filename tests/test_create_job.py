"""Tests for job creation endpoint.

Verifies that the API correctly accepts valid bulk generation requests
and returns appropriate responses.
"""


def test_create_job_returns_202(client, sample_job_payload):
    """A valid request should return 202 Accepted with job details."""
    response = client.post("/api/v1/jobs", json=sample_job_payload)
    assert response.status_code == 202

    data = response.json()
    assert data["status"] == "pending"
    assert data["total_recipients"] == 3
    assert data["successful_count"] == 0
    assert data["failed_count"] == 0
    assert "id" in data


def test_create_job_with_single_recipient(client):
    """A job with just one recipient should work fine."""
    payload = {
        "recipients": [
            {
                "name": "Solo Participant",
                "course_name": "Intro to AI",
                "date": "2024-06-01",
            }
        ]
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 202
    assert response.json()["total_recipients"] == 1


def test_create_job_with_empty_recipients_returns_422(client):
    """An empty recipients list should be rejected."""
    payload = {"recipients": []}
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422


def test_create_job_with_invalid_template_returns_400(client, sample_recipients):
    """A non-existent template ID should return 400."""
    payload = {
        "recipients": sample_recipients,
        "template_id": "nonexistent_template",
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


def test_create_job_uses_default_template(client, sample_recipients):
    """If no template_id is given, it should default to 'classic'."""
    payload = {"recipients": sample_recipients}
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 202
    assert response.json()["template_id"] == "classic"


def test_root_serves_html_ui(client):
    """GET / should serve the Web UI HTML."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Bulk Certificate Generator" in response.text
