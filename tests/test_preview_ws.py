"""Tests for WebSocket real-time live preview and template layout positioning endpoints."""

import io
import os
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.models import Template
from app.schemas import TemplateLayoutUpdate


def test_websocket_ping_pong(client: TestClient):
    """WebSocket should respond with pong to ping messages."""
    with client.websocket_connect("/api/v1/ws/preview") as ws:
        ws.send_json({"action": "ping"})
        msg = ws.receive_json()
        assert msg["action"] == "pong"


def test_websocket_update_coords(client: TestClient):
    """WebSocket should acknowledge coordinate updates and return formatted coords."""
    with client.websocket_connect("/api/v1/ws/preview") as ws:
        ws.send_json({
            "action": "update_coords",
            "template_id": "classic",
            "name_x": 0.5234,
            "name_y": 0.6123,
            "course_x": 0.55,
            "course_y": 0.45,
            "date_x": 0.58,
            "date_y": 0.32,
            "show_course": True,
            "show_date": False,
        })
        msg = ws.receive_json()
        assert msg["action"] == "coords_updated"
        assert msg["status"] == "ok"
        coords = msg["coords"]
        assert coords["name_x"] == 0.523
        assert coords["name_y"] == 0.612
        assert coords["show_course"] is True
        assert coords["show_date"] is False


def test_websocket_save_coords_updates_db(client: TestClient, db_session):
    """WebSocket save_coords action should persist new layout coordinates into database."""
    # Create a template in test database
    tmpl = Template(
        id="test-ws-tmpl",
        name="test_ws_tmpl",
        description="Template for WS test",
        is_builtin=0,
        name_x_ratio=0.5,
        name_y_ratio=0.5,
    )
    db_session.add(tmpl)
    db_session.commit()

    with client.websocket_connect("/api/v1/ws/preview") as ws:
        ws.send_json({
            "action": "save_coords",
            "template_id": "test-ws-tmpl",
            "name_x": 0.45,
            "name_y": 0.65,
            "course_x": 0.48,
            "course_y": 0.42,
            "date_x": 0.52,
            "date_y": 0.30,
            "show_course": True,
            "show_date": True,
        })
        msg = ws.receive_json()
        assert msg["action"] == "coords_saved"
        assert msg["status"] == "ok"
        assert msg["template_id"] == "test-ws-tmpl"

    # Verify directly in database
    db_session.expire_all()
    updated = db_session.query(Template).filter(Template.id == "test-ws-tmpl").first()
    assert updated.name_x_ratio == 0.45
    assert updated.name_y_ratio == 0.65
    assert updated.course_x_ratio == 0.48
    assert updated.course_y_ratio == 0.42
    assert updated.date_x_ratio == 0.52
    assert updated.date_y_ratio == 0.30
    assert updated.show_course == 1
    assert updated.show_date == 1
    assert updated.overlay_mode == "preprinted"


def test_websocket_save_coords_nonexistent_template(client: TestClient):
    """WebSocket save_coords for non-existent template returns error."""
    with client.websocket_connect("/api/v1/ws/preview") as ws:
        ws.send_json({
            "action": "save_coords",
            "template_id": "does-not-exist",
            "name_x": 0.5,
            "name_y": 0.5,
        })
        msg = ws.receive_json()
        assert msg["action"] == "error"
        assert "not found" in msg["detail"].lower()


def test_put_template_layout_endpoint(client: TestClient, db_session):
    """REST PUT /api/v1/templates/{id}/layout should update coordinates and return TemplateResponse."""
    tmpl = Template(
        id="test-layout-tmpl",
        name="test_layout_tmpl",
        is_builtin=0,
    )
    db_session.add(tmpl)
    db_session.commit()

    res = client.put(
        "/api/v1/templates/test-layout-tmpl/layout",
        json={
            "name_x_ratio": 0.55,
            "name_y_ratio": 0.58,
            "course_x_ratio": 0.52,
            "course_y_ratio": 0.44,
            "date_x_ratio": 0.60,
            "date_y_ratio": 0.35,
            "show_course": True,
            "show_date": False,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name_x_ratio"] == 0.55
    assert data["name_y_ratio"] == 0.58
    assert data["course_x_ratio"] == 0.52
    assert data["course_y_ratio"] == 0.44
    assert data["date_x_ratio"] == 0.60
    assert data["date_y_ratio"] == 0.35
    assert data["show_course"] is True
    assert data["show_date"] is False


def test_put_template_layout_nonexistent_returns_404(client: TestClient):
    """REST PUT for non-existent template returns 404."""
    res = client.put(
        "/api/v1/templates/nonexistent/layout",
        json={"name_x_ratio": 0.5, "name_y_ratio": 0.5},
    )
    assert res.status_code == 404


def test_get_template_background_builtin(client: TestClient):
    """GET /api/v1/templates/{id}/background should return background image for classic template."""
    res = client.get("/api/v1/templates/classic/background")
    assert res.status_code == 200
    assert res.headers["content-type"] in ("image/png", "image/jpeg")
    assert len(res.content) > 100


def test_get_template_background_custom_png(client: TestClient, tmp_path, db_session):
    """GET /api/v1/templates/{id}/background should return user-uploaded image."""
    # Create dummy PNG image file
    img = Image.new("RGB", (600, 400), color=(240, 240, 250))
    img_path = str(tmp_path / "custom_bg.png")
    img.save(img_path)

    tmpl = Template(
        id="custom-bg-tmpl",
        name="custom_bg_tmpl",
        file_path=img_path,
        is_builtin=0,
    )
    db_session.add(tmpl)
    db_session.commit()

    res = client.get("/api/v1/templates/custom-bg-tmpl/background")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert len(res.content) > 0


def test_get_template_background_nonexistent_returns_404(client: TestClient):
    """GET background for non-existent template should return 404."""
    res = client.get("/api/v1/templates/nonexistent/background")
    assert res.status_code == 404


def test_generation_uses_calibrated_layout_coords(client: TestClient, tmp_path, db_session):
    """Bulk job generation should use custom positioned coordinates saved on the template."""
    img = Image.new("RGB", (800, 600), color=(255, 255, 255))
    img_path = str(tmp_path / "calibrated_tmpl.png")
    img.save(img_path)

    tmpl = Template(
        id="calibrated-tmpl",
        name="calibrated_tmpl",
        file_path=img_path,
        is_builtin=0,
        overlay_mode="preprinted",
        name_x_ratio=0.60,
        name_y_ratio=0.70,
        course_x_ratio=0.60,
        course_y_ratio=0.50,
        date_x_ratio=0.60,
        date_y_ratio=0.30,
        show_course=1,
        show_date=1,
    )
    db_session.add(tmpl)
    db_session.commit()

    payload = {
        "template_id": "calibrated-tmpl",
        "recipients": [
            {
                "name": "Samantha Reed",
                "course_name": "Autonomous Drone Navigation",
                "date": "2024-12-15",
            }
        ],
    }

    res = client.post("/api/v1/jobs", json=payload)
    assert res.status_code == 202
    job_id = res.json()["id"]

    import time
    time.sleep(0.5)

    status_res = client.get(f"/api/v1/jobs/{job_id}")
    data = status_res.json()
    assert data["status"] == "completed"
    assert data["successful_count"] == 1
    assert data["failed_count"] == 0
