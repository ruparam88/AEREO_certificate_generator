"""Tests for certificate retrieval and download.

Verifies that generated certificates can be downloaded individually
or as a bulk ZIP archive.
"""

import time


def test_download_certificate_returns_pdf(client, sample_job_payload):
    """Downloading a successful certificate should return a PDF."""
    response = client.post("/api/v1/jobs", json=sample_job_payload)
    job_id = response.json()["id"]
    time.sleep(0.5)

    # Get certificates
    certs = client.get(f"/api/v1/jobs/{job_id}/certificates").json()
    success_certs = [c for c in certs if c["status"] == "success"]
    assert len(success_certs) > 0

    # Download the first one
    download_url = success_certs[0]["download_url"]
    download = client.get(download_url)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content[:5] == b"%PDF-"


def test_download_nonexistent_certificate_returns_404(client):
    """Requesting a non-existent certificate should return 404."""
    response = client.get("/api/v1/certificates/nonexistent-id/download")
    assert response.status_code == 404


def test_list_certificates_for_job(client, sample_job_payload):
    """Listing certificates should return all with their statuses."""
    response = client.post("/api/v1/jobs", json=sample_job_payload)
    job_id = response.json()["id"]
    time.sleep(0.5)

    certs = client.get(f"/api/v1/jobs/{job_id}/certificates").json()
    assert len(certs) == 3
    for cert in certs:
        assert "status" in cert
        assert "recipient_name" in cert
        assert "id" in cert


def test_download_all_as_zip(client, sample_job_payload):
    """Download-all endpoint should return a valid ZIP file."""
    response = client.post("/api/v1/jobs", json=sample_job_payload)
    job_id = response.json()["id"]
    time.sleep(0.5)

    zip_response = client.get(f"/api/v1/jobs/{job_id}/download-all")
    assert zip_response.status_code == 200
    assert "application/zip" in zip_response.headers["content-type"]
    # ZIP files start with PK magic bytes
    assert zip_response.content[:2] == b"PK"


def test_download_all_for_nonexistent_job_returns_404(client):
    """Download-all for a non-existent job should return 404."""
    response = client.get("/api/v1/jobs/nonexistent/download-all")
    assert response.status_code == 404


def test_templates_endpoint(client):
    """The templates endpoint should list built-in templates."""
    response = client.get("/api/v1/templates")
    assert response.status_code == 200
    templates = response.json()
    assert len(templates) >= 3
    names = [t["name"] for t in templates]
    assert "classic" in names
    assert "modern" in names
    assert "elegant" in names


def test_upload_custom_template_and_use_in_job(client, tmp_path):
    """Test uploading a custom PNG template and generating a certificate with it."""
    import io
    from PIL import Image

    # Create a dummy image in memory
    img = Image.new("RGB", (800, 600), color=(240, 240, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    # Upload template
    upload_resp = client.post(
        "/api/v1/templates/upload",
        data={"name": "custom_blue", "description": "Custom blue template"},
        files={"file": ("custom_blue.png", buf, "image/png")},
    )
    assert upload_resp.status_code == 201
    template_data = upload_resp.json()
    assert template_data["name"] == "custom_blue"
    assert template_data["is_builtin"] is False
    template_id = template_data["id"]

    # Submit job using this template
    job_payload = {
        "recipients": [
            {
                "name": "Custom Template Recipient",
                "course_name": "Custom Course",
                "date": "2024-05-20",
            }
        ],
        "template_id": template_id,
    }
    job_resp = client.post("/api/v1/jobs", json=job_payload)
    assert job_resp.status_code == 202
    job_id = job_resp.json()["id"]

    # Verify job status
    status = client.get(f"/api/v1/jobs/{job_id}").json()
    assert status["status"] == "completed"
    assert status["successful_count"] == 1


def test_upload_template_unsupported_file_type_returns_400(client):
    """Uploading an unsupported file format like text should return 400."""
    import io
    buf = io.BytesIO(b"hello text")
    resp = client.post(
        "/api/v1/templates/upload",
        data={"name": "invalid_template"},
        files={"file": ("test.txt", buf, "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_duplicate_template_name_returns_409(client):
    """Uploading with an existing template name should return 409 conflict."""
    import io
    from PIL import Image

    img = Image.new("RGB", (100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    # classic already exists
    resp = client.post(
        "/api/v1/templates/upload",
        data={"name": "classic"},
        files={"file": ("classic.png", buf, "image/png")},
    )
    assert resp.status_code == 409


def test_delete_custom_template(client):
    """Deleting a custom template should remove it from DB and disk."""
    import io
    from PIL import Image

    img = Image.new("RGB", (100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    # Upload
    upload_resp = client.post(
        "/api/v1/templates/upload",
        data={"name": "to_delete"},
        files={"file": ("to_delete.png", buf, "image/png")},
    )
    assert upload_resp.status_code == 201
    tmpl_id = upload_resp.json()["id"]

    # Delete
    del_resp = client.delete(f"/api/v1/templates/{tmpl_id}")
    assert del_resp.status_code == 200
    assert "deleted successfully" in del_resp.json()["message"]

    # Verify not in list
    list_resp = client.get("/api/v1/templates")
    ids = [t["id"] for t in list_resp.json()]
    assert tmpl_id not in ids


def test_delete_builtin_template_fails(client):
    """Attempting to delete a built-in template should return 400 Bad Request."""
    resp = client.delete("/api/v1/templates/classic")
    assert resp.status_code == 400
    assert "cannot delete built-in" in resp.json()["detail"].lower()


def test_delete_nonexistent_template_fails(client):
    """Attempting to delete a non-existent template should return 404."""
    resp = client.delete("/api/v1/templates/nonexistent_123")
    assert resp.status_code == 404


def test_clear_all_custom_templates(client):
    """Clearing all custom templates should leave only built-in ones."""
    import io
    from PIL import Image

    for name in ["custom_1", "custom_2"]:
        img = Image.new("RGB", (100, 100))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        client.post(
            "/api/v1/templates/upload",
            data={"name": name},
            files={"file": (f"{name}.png", buf, "image/png")},
        )

    # Clear all custom
    clear_resp = client.delete("/api/v1/templates/custom/clear-all")
    assert clear_resp.status_code == 200
    assert clear_resp.json()["count"] >= 2

    # Verify only built-in templates remain
    list_resp = client.get("/api/v1/templates")
    templates = list_resp.json()
    assert all(t["is_builtin"] for t in templates)


def test_upload_template_with_overwrite(client):
    """Uploading with overwrite=True should replace the existing custom template."""
    import io
    from PIL import Image

    img1 = Image.new("RGB", (100, 100))
    buf1 = io.BytesIO()
    img1.save(buf1, format="PNG")
    buf1.seek(0)

    # Initial upload
    resp1 = client.post(
        "/api/v1/templates/upload",
        data={"name": "replaceable", "description": "version 1"},
        files={"file": ("v1.png", buf1, "image/png")},
    )
    assert resp1.status_code == 201

    # Overwrite upload
    img2 = Image.new("RGB", (200, 200))
    buf2 = io.BytesIO()
    img2.save(buf2, format="PNG")
    buf2.seek(0)

    resp2 = client.post(
        "/api/v1/templates/upload",
        data={"name": "replaceable", "description": "version 2", "overwrite": "true"},
        files={"file": ("v2.png", buf2, "image/png")},
    )
    assert resp2.status_code in (200, 201)
    data2 = resp2.json()
    assert data2["name"] == "replaceable"
    assert data2["description"] == "version 2"


def test_upload_template_with_font_and_color_customization(client):
    """Uploading with explicit font_family and color overrides should save those styles."""
    import io
    from PIL import Image

    img = Image.new("RGB", (200, 200), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    resp = client.post(
        "/api/v1/templates/upload",
        data={
            "name": "styled_template",
            "description": "Custom fonts and colors",
            "font_family": "serif",
            "primary_color": "#0A001D",
            "accent_color": "#609AAD",
        },
        files={"file": ("styled.png", buf, "image/png")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "styled_template"
    assert data["font_family"] == "serif"
    assert data["primary_color"] == "#0A001D"
    assert data["accent_color"] == "#609AAD"
