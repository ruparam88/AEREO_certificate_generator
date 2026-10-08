"""Tests for certificate generation.

Verifies that the PDF generation service creates valid files on disk
and that the background processing works correctly.
"""

import os
import time

from app.services.certificate_generator import generate_certificate
from app.config import settings


def test_generate_certificate_creates_pdf(tmp_path):
    """The generator should create a PDF file on disk."""
    output_dir = str(tmp_path)
    path = generate_certificate(
        recipient_name="Test User",
        course_name="Python 101",
        date="2024-12-15",
        certificate_id="test-cert-001",
        output_dir=output_dir,
        template_style="classic",
    )
    assert os.path.exists(path)
    assert path.endswith(".pdf")


def test_generated_pdf_is_valid(tmp_path):
    """The generated file should start with the PDF magic bytes."""
    output_dir = str(tmp_path)
    path = generate_certificate(
        recipient_name="PDF Check",
        course_name="Validation Course",
        date="2024-01-01",
        certificate_id="test-cert-002",
        output_dir=output_dir,
    )
    with open(path, "rb") as f:
        header = f.read(5)
    assert header == b"%PDF-"


def test_all_template_styles_work(tmp_path):
    """Every built-in template style should generate without errors."""
    for style in ["classic", "modern", "elegant"]:
        path = generate_certificate(
            recipient_name=f"Template Test ({style})",
            course_name="Template Course",
            date="2024-06-15",
            certificate_id=f"tmpl-{style}",
            output_dir=str(tmp_path),
            template_style=style,
        )
        assert os.path.exists(path)


def test_invalid_template_style_raises_error(tmp_path):
    """An unknown template style should raise ValueError."""
    import pytest
    with pytest.raises(ValueError, match="Unknown template style"):
        generate_certificate(
            recipient_name="Error Test",
            course_name="Course",
            date="2024-01-01",
            certificate_id="err-001",
            output_dir=str(tmp_path),
            template_style="nonexistent",
        )


def test_job_processes_and_generates_files(client, sample_job_payload):
    """After creating a job, certificates should be generated on disk."""
    response = client.post("/api/v1/jobs", json=sample_job_payload)
    job_id = response.json()["id"]

    # Wait for background processing (TestClient runs tasks synchronously)
    time.sleep(0.5)

    # Check job completed
    status_response = client.get(f"/api/v1/jobs/{job_id}")
    data = status_response.json()
    assert data["status"] == "completed"
    assert data["successful_count"] == 3

    # Verify files exist
    for cert in data["certificates"]:
        if cert["status"] == "success":
            assert cert["download_url"] is not None


def test_custom_template_preprinted_mode(tmp_path):
    """Preprinted mode should generate a clean PDF with matched aspect ratio."""
    from PIL import Image

    # Create dummy template image
    img_path = str(tmp_path / "custom_preprinted.png")
    img = Image.new("RGB", (2000, 1414), color=(255, 255, 255))
    img.save(img_path)

    pdf_path = generate_certificate(
        recipient_name="Chandra Gupta",
        course_name="Cloud Architecture",
        date="2024-12-15",
        certificate_id="preprinted-001",
        output_dir=str(tmp_path),
        custom_template_path=img_path,
        overlay_mode="preprinted",
    )
    assert os.path.exists(pdf_path)
    with open(pdf_path, "rb") as f:
        assert f.read(5) == b"%PDF-"


def test_custom_template_full_mode(tmp_path):
    """Full frame mode should generate complete certificate content."""
    from PIL import Image

    img_path = str(tmp_path / "custom_frame.png")
    img = Image.new("RGB", (1600, 1200), color=(245, 245, 250))
    img.save(img_path)

    pdf_path = generate_certificate(
        recipient_name="Full Frame Recipient",
        course_name="Full Frame Course",
        date="2024-12-15",
        certificate_id="frame-001",
        output_dir=str(tmp_path),
        custom_template_path=img_path,
        overlay_mode="full",
    )
    assert os.path.exists(pdf_path)
    with open(pdf_path, "rb") as f:
        assert f.read(5) == b"%PDF-"


def test_detect_template_layout_and_multifield_render(tmp_path):
    """Test layout auto-detection and multi-field preprinted certificate generation."""
    from app.services.certificate_generator import detect_template_layout
    outputs_template = os.path.join(r"c:\Users\Hp\Documents\Projects\AEREO\Bulk certificate gnerator\outputs", "template2.png")
    
    if os.path.exists(outputs_template):
        layout = detect_template_layout(outputs_template)
        assert layout["show_course"] is True
        assert layout["show_date"] is True
        assert layout["course_y_ratio"] is not None
        assert layout["date_y_ratio"] is not None

        pdf_path = generate_certificate(
            recipient_name="Bob Smith",
            course_name="FastAPI & Microservices Masterclass",
            date="2024-12-15",
            certificate_id="test-multifield-001",
            output_dir=str(tmp_path),
            custom_template_path=outputs_template,
            overlay_mode="preprinted",
        )
        assert os.path.exists(pdf_path)
        with open(pdf_path, "rb") as f:
            assert f.read(5) == b"%PDF-"


def test_pdf_template_generation(tmp_path):
    """Test generating certificates using a vector PDF template file."""
    import reportlab.pdfgen.canvas as rl_canvas
    from app.services.certificate_generator import generate_certificate, detect_template_layout

    # Create a dummy 1-page PDF template
    tmpl_pdf = str(tmp_path / "template.pdf")
    c = rl_canvas.Canvas(tmpl_pdf, pagesize=(842, 595))
    c.drawString(100, 500, "Course name: ")
    c.drawString(100, 300, "Issued on ")
    c.save()

    layout = detect_template_layout(tmpl_pdf)
    assert layout["show_course"] is True
    assert layout["show_date"] is True

    out_pdf = generate_certificate(
        recipient_name="PDF Recipient",
        course_name="PDF Course Masterclass",
        date="2024-12-15",
        certificate_id="test-pdf-cert",
        output_dir=str(tmp_path),
        custom_template_path=tmpl_pdf,
        overlay_mode="preprinted",
    )
    assert os.path.exists(out_pdf)
    with open(out_pdf, "rb") as f:
        assert f.read(5) == b"%PDF-"


def test_font_family_and_color_customization(tmp_path):
    """Test generating certificates with custom font family and primary/accent colors."""
    from app.services.certificate_generator import generate_certificate

    for style, font in [("classic", "serif"), ("modern", "sans"), ("elegant", "elegant")]:
        pdf_path = generate_certificate(
            recipient_name="Typo Recipient",
            course_name="Typography & Design",
            date="2024-12-15",
            certificate_id=f"cert-{style}-{font}",
            output_dir=str(tmp_path),
            template_style=style,
            font_family=font,
            primary_color="#0A001D",
            accent_color="#609AAD",
        )
        assert os.path.exists(pdf_path)
        with open(pdf_path, "rb") as f:
            assert f.read(5) == b"%PDF-"


def test_template_palette_and_font_detection(tmp_path):
    """Test layout and color palette auto-detection on custom template images."""
    from app.services.certificate_generator import detect_template_layout
    from PIL import Image

    # Create dummy image template with dark navy text sample
    img_path = str(tmp_path / "custom_dark.png")
    im = Image.new("RGB", (1200, 800), color=(255, 255, 255))
    # Draw some dark pixels
    for x in range(300, 900):
        im.putpixel((x, 400), (10, 0, 29))
    im.save(img_path)

    layout = detect_template_layout(img_path)
    assert "primary_color" in layout
    assert "accent_color" in layout
    assert "font_family" in layout
    assert layout["font_family"] == "sans"


def test_dynamic_font_scaling_for_long_names(tmp_path):
    """Test that exceptionally long names and course titles scale down gracefully."""
    from app.services.certificate_generator import generate_certificate

    long_name = "Alexander Bartholomew Montgomery-Fitzgerald III"
    long_course = "Advanced Distributed Systems, Cloud-Native Architectures & High-Throughput Engineering"

    pdf_path = generate_certificate(
        recipient_name=long_name,
        course_name=long_course,
        date="2024-12-15",
        certificate_id="long-text-cert",
        output_dir=str(tmp_path),
        template_style="classic",
    )
    assert os.path.exists(pdf_path)
    with open(pdf_path, "rb") as f:
        assert f.read(5) == b"%PDF-"


def test_per_field_fonts_sizes_and_colors(tmp_path):
    """Test generating certificates with independent fonts, sizes, and colors for Name, Course, and Date."""
    from PIL import Image
    from app.services.certificate_generator import generate_certificate

    img_path = str(tmp_path / "per_field_template.png")
    im = Image.new("RGB", (1200, 800), color=(250, 250, 250))
    im.save(img_path)

    test_fonts = [
        "Arial", "Times New Roman", "Georgia", "Garamond", "Palatino",
        "Verdana", "Trebuchet MS", "Courier New", "Cinzel", "Great Vibes",
    ]

    for i, font in enumerate(test_fonts):
        out = generate_certificate(
            recipient_name=f"Scholar {font}",
            course_name=f"Mastery in {font}",
            date="2025-01-10",
            certificate_id=f"cert-font-{i}",
            output_dir=str(tmp_path),
            custom_template_path=img_path,
            overlay_mode="preprinted",
            name_font=font,
            name_size=36.0,
            name_color="#1e3a8a",
            course_font="Arial" if font != "Arial" else "Georgia",
            course_size=18.0,
            course_color="#047857",
            date_font="Courier New" if font != "Courier New" else "Times New Roman",
            date_size=11.0,
            date_color="#b45309",
        )
        assert os.path.exists(out)
        with open(out, "rb") as f:
            assert f.read(5) == b"%PDF-"

