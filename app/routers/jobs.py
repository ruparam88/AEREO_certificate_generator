"""API endpoints for certificate generation jobs.

This router handles the full lifecycle of a bulk certificate generation
request:
    1. POST /jobs        — Submit a new bulk generation request
    2. GET  /jobs        — List all jobs (with pagination)
    3. GET  /jobs/{id}   — Check job status and progress
    4. GET  /jobs/{id}/certificates — List certificates with download URLs
    5. GET  /certificates/{id}/download — Download a single PDF
    6. GET  /jobs/{id}/download-all — Download all certificates as ZIP
    7. GET  /templates   — List available templates
    8. POST /templates/upload — Upload a custom template
"""

import io
import os
import zipfile
from typing import Optional

from fastapi import (
    APIRouter, BackgroundTasks, Depends, HTTPException, Query,
    UploadFile, File, Form, WebSocket, WebSocketDisconnect, Response,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import Job, Certificate, Template, CertificateStatus
from app.schemas import (
    JobCreate, JobResponse, JobDetailResponse,
    CertificateResponse, TemplateResponse, RecipientCreate, TemplateLayoutUpdate,
)
from app.services.job_service import create_job, process_job
from app.services.certificate_generator import detect_template_layout
from app.services.sheet_parser import parse_recipients_file
from app.config import settings

router = APIRouter(tags=["Certificate Jobs"])


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@router.post(
    "/jobs",
    response_model=JobResponse,
    status_code=202,
    summary="Submit a bulk certificate generation request",
)
def create_generation_job(
    job_data: JobCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Accept a list of recipients and start generating certificates.

    The job is created immediately and returned with status 'pending'.
    Certificate generation happens in the background — poll the job
    status endpoint to track progress.

    Returns:
        202 Accepted with the job details.
    """
    try:
        job = create_job(db, job_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Enqueue background processing
    background_tasks.add_task(process_job, job.id)

    return job


@router.post(
    "/recipients/parse-file",
    response_model=list[RecipientCreate],
    summary="Parse recipients from an Excel (.xlsx) or CSV (.csv) spreadsheet",
)
async def parse_spreadsheet_file(
    file: UploadFile = File(..., description="Excel (.xlsx) or CSV (.csv) file"),
):
    """Upload an Excel (.xlsx) or CSV (.csv) spreadsheet and extract validated recipients.

    Supports intelligent column matching (Name, Course, Date, Email).
    Returns the parsed and validated recipient list ready for verification or job submission.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        recipients = parse_recipients_file(content, file.filename or "file.csv")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return recipients


@router.post(
    "/jobs/upload-sheet",
    response_model=JobResponse,
    status_code=202,
    summary="Submit bulk generation job directly from an Excel (.xlsx) or CSV (.csv) spreadsheet",
)
async def create_job_from_spreadsheet(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Excel (.xlsx) or CSV (.csv) file"),
    template_id: str = Form("classic", description="Template ID to use"),
    db: Session = Depends(get_db),
):
    """Upload a spreadsheet directly and start generating certificates in the background."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        recipients = parse_recipients_file(content, file.filename or "file.csv")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    job_data = JobCreate(recipients=recipients, template_id=template_id)
    try:
        job = create_job(db, job_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    background_tasks.add_task(process_job, job.id)
    return job


@router.get(
    "/jobs",
    response_model=list[JobResponse],
    summary="List all jobs",
)
def list_jobs(
    skip: int = Query(0, ge=0, description="Number of jobs to skip"),
    limit: int = Query(20, ge=1, le=100, description="Max jobs to return"),
    db: Session = Depends(get_db),
):
    """List all jobs, most recent first, with pagination."""
    jobs = (
        db.query(Job)
        .order_by(Job.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return jobs


@router.get(
    "/jobs/{job_id}",
    response_model=JobDetailResponse,
    summary="Get job status and details",
)
def get_job(job_id: str, db: Session = Depends(get_db)):
    """Get the full details of a job including all certificate records.

    The response includes:
    - Job status and progress counts
    - Every certificate with its status and download URL
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Build response with download URLs for successful certificates
    cert_responses = []
    for cert in job.certificates:
        download_url = None
        if cert.status == CertificateStatus.SUCCESS and cert.file_path:
            download_url = f"/api/v1/certificates/{cert.id}/download"
        cert_responses.append(
            CertificateResponse(
                id=cert.id,
                recipient_name=cert.recipient_name,
                recipient_email=cert.recipient_email,
                course_name=cert.course_name,
                date=cert.date,
                status=cert.status,
                error_message=cert.error_message,
                download_url=download_url,
            )
        )

    return JobDetailResponse(
        id=job.id,
        status=job.status,
        template_id=job.template_id,
        total_recipients=job.total_recipients,
        successful_count=job.successful_count,
        failed_count=job.failed_count,
        created_at=job.created_at,
        completed_at=job.completed_at,
        certificates=cert_responses,
    )


@router.get(
    "/jobs/{job_id}/certificates",
    response_model=list[CertificateResponse],
    summary="List certificates for a job",
)
def list_certificates(job_id: str, db: Session = Depends(get_db)):
    """List all certificates belonging to a job with download URLs."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    results = []
    for cert in job.certificates:
        download_url = None
        if cert.status == CertificateStatus.SUCCESS and cert.file_path:
            download_url = f"/api/v1/certificates/{cert.id}/download"
        results.append(
            CertificateResponse(
                id=cert.id,
                recipient_name=cert.recipient_name,
                recipient_email=cert.recipient_email,
                course_name=cert.course_name,
                date=cert.date,
                status=cert.status,
                error_message=cert.error_message,
                download_url=download_url,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Certificate Download
# ---------------------------------------------------------------------------

@router.get(
    "/certificates/{certificate_id}/download",
    summary="Download a single certificate PDF",
)
def download_certificate(certificate_id: str, db: Session = Depends(get_db)):
    """Download a generated certificate as a PDF file.

    Returns 404 if the certificate doesn't exist or failed to generate.
    """
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    if cert.status != CertificateStatus.SUCCESS or not cert.file_path:
        raise HTTPException(
            status_code=404,
            detail="Certificate has not been generated successfully",
        )

    if not os.path.exists(cert.file_path):
        raise HTTPException(
            status_code=404,
            detail="Certificate file not found on disk",
        )

    # Sanitize filename for download
    safe_name = cert.recipient_name.replace(" ", "_").replace("/", "_")
    filename = f"certificate_{safe_name}.pdf"

    return FileResponse(
        path=cert.file_path,
        media_type="application/pdf",
        filename=filename,
    )


@router.get(
    "/jobs/{job_id}/download-all",
    summary="Download all certificates for a job as a ZIP file",
)
def download_all_certificates(job_id: str, db: Session = Depends(get_db)):
    """Download all successfully generated certificates as a single ZIP.

    Only includes certificates with status 'success'. Streams the ZIP
    directly to the client without writing it to disk first.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Collect successful certificates that have files on disk
    successful_certs = [
        cert for cert in job.certificates
        if cert.status == CertificateStatus.SUCCESS
        and cert.file_path
        and os.path.exists(cert.file_path)
    ]

    if not successful_certs:
        raise HTTPException(
            status_code=404,
            detail="No successfully generated certificates found",
        )

    # Build ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for cert in successful_certs:
            safe_name = cert.recipient_name.replace(" ", "_").replace("/", "_")
            archive_name = f"certificate_{safe_name}_{cert.id[:8]}.pdf"
            zf.write(cert.file_path, archive_name)

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=certificates_job_{job_id[:8]}.zip"
        },
    )


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

@router.get(
    "/templates",
    response_model=list[TemplateResponse],
    summary="List available certificate templates",
)
def list_templates(db: Session = Depends(get_db)):
    """List all available templates (built-in and user-uploaded)."""
    templates = db.query(Template).all()
    return [TemplateResponse.model_validate(t) for t in templates]


@router.post(
    "/templates/upload",
    response_model=TemplateResponse,
    status_code=201,
    summary="Upload a custom certificate template",
)
def upload_template(
    name: str = Form(..., description="Template name"),
    description: str = Form(None, description="Template description"),
    overlay_mode: str = Form(
        "preprinted",
        description="Overlay mode: 'preprinted' (for full certificates like Canva templates) or 'full' (for blank frames)",
    ),
    name_y_ratio: float = Form(
        0.515,
        description="Vertical position ratio of recipient name from bottom (default 0.515)",
    ),
    name_x_ratio: float = Form(
        0.5,
        description="Horizontal center ratio of recipient name from left (default 0.5)",
    ),
    overwrite: bool = Form(
        False,
        description="Overwrite existing template if a template with the same name already exists",
    ),
    font_family: Optional[str] = Form(
        None,
        description="Font style: 'sans' (Modern Sans-Serif), 'serif' (Classical Serif), 'elegant' (Executive Serif)",
    ),
    primary_color: Optional[str] = Form(
        None,
        description="Primary text hex color e.g. '#0A001D' (leave blank to auto-detect)",
    ),
    accent_color: Optional[str] = Form(
        None,
        description="Accent hex color e.g. '#609AAD' (leave blank to auto-detect)",
    ),
    file: UploadFile = File(..., description="Template image (PNG, JPEG, or PDF)"),
    db: Session = Depends(get_db),
):
    """Upload a custom image to use as a certificate background.

    Supported formats: PNG, JPEG, PDF.
    The uploaded file is saved to the server's templates directory.
    If overwrite is True, updates an existing custom template with the same name.
    """
    # Validate file type
    allowed_types = {"image/png", "image/jpeg", "application/pdf"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{file.content_type}'. "
                   f"Allowed: PNG, JPEG, PDF.",
        )

    # Check name uniqueness
    existing = db.query(Template).filter(Template.name == name).first()
    if existing:
        if not overwrite:
            raise HTTPException(
                status_code=409,
                detail=f"Template with name '{name}' already exists. Enable overwrite to update it or delete the existing template.",
            )
        if existing.is_builtin:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot overwrite built-in system template '{name}'",
            )

    # Save uploaded file
    os.makedirs(settings.uploaded_templates_dir, exist_ok=True)
    ext = file.filename.split(".")[-1] if file.filename else "png"
    from uuid import uuid4
    template_id = existing.id if existing else str(uuid4())
    save_path = os.path.join(settings.uploaded_templates_dir, f"{template_id}.{ext}")

    with open(save_path, "wb") as f:
        content = file.file.read()
        f.write(content)

    # Run auto-detection on template layout and color palette
    course_y_ratio = None
    course_x_ratio = None
    date_y_ratio = None
    date_x_ratio = None
    show_course = 1
    show_date = 1

    layout = detect_template_layout(os.path.abspath(save_path))
    if layout:
        if overlay_mode == "preprinted":
            if name_y_ratio == 0.515 and "name_y_ratio" in layout:
                name_y_ratio = layout["name_y_ratio"]
            course_y_ratio = layout.get("course_y_ratio")
            course_x_ratio = layout.get("course_x_ratio")
            date_y_ratio = layout.get("date_y_ratio")
            date_x_ratio = layout.get("date_x_ratio")
            show_course = 1 if layout.get("show_course", True) else 0
            show_date = 1 if layout.get("show_date", True) else 0

        # Auto-detect typography and colors if not explicitly overridden by user
        if not font_family and "font_family" in layout:
            font_family = layout["font_family"]
        if not primary_color and "primary_color" in layout:
            primary_color = layout["primary_color"]
        if not accent_color and "accent_color" in layout:
            accent_color = layout["accent_color"]

    font_family = font_family or "sans"
    primary_color = primary_color or "#1E293B"
    accent_color = accent_color or "#2E86AB"

    if existing:
        # Overwrite existing record
        existing.description = description
        existing.file_path = os.path.abspath(save_path)
        existing.overlay_mode = overlay_mode
        existing.name_y_ratio = name_y_ratio
        existing.name_x_ratio = name_x_ratio
        existing.course_y_ratio = course_y_ratio
        existing.course_x_ratio = course_x_ratio
        existing.date_y_ratio = date_y_ratio
        existing.date_x_ratio = date_x_ratio
        existing.show_course = show_course
        existing.show_date = show_date
        existing.font_family = font_family
        existing.primary_color = primary_color
        existing.accent_color = accent_color
        db.commit()
        db.refresh(existing)
        return TemplateResponse.model_validate(existing)

    # Create new database record
    template = Template(
        id=template_id,
        name=name,
        description=description,
        file_path=os.path.abspath(save_path),
        is_builtin=0,
        overlay_mode=overlay_mode,
        name_y_ratio=name_y_ratio,
        name_x_ratio=name_x_ratio,
        course_y_ratio=course_y_ratio,
        course_x_ratio=course_x_ratio,
        date_y_ratio=date_y_ratio,
        date_x_ratio=date_x_ratio,
        show_course=show_course,
        show_date=show_date,
        font_family=font_family,
        primary_color=primary_color,
        accent_color=accent_color,
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    return TemplateResponse.model_validate(template)


@router.delete(
    "/templates/custom/clear-all",
    summary="Clear all user-uploaded custom templates",
)
def clear_all_custom_templates(db: Session = Depends(get_db)):
    """Delete all user-uploaded templates and remove their files from disk.

    Built-in templates ('classic', 'modern', 'elegant') are preserved.
    """
    custom_templates = db.query(Template).filter(Template.is_builtin == 0).all()
    count = len(custom_templates)
    for t in custom_templates:
        if t.file_path and os.path.exists(t.file_path):
            try:
                os.remove(t.file_path)
            except OSError:
                pass
        db.delete(t)
    db.commit()
    return {"message": f"Successfully deleted {count} custom templates", "count": count}


@router.delete(
    "/templates/{template_id}",
    summary="Delete a custom certificate template",
)
def delete_template(template_id: str, db: Session = Depends(get_db)):
    """Delete a custom template by ID or Name.

    Removes the template record, associated file from disk, and any associated jobs.
    Built-in templates cannot be deleted.
    """
    template = db.query(Template).filter(
        (Template.id == template_id) | (Template.name == template_id)
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    if template.is_builtin:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete built-in template '{template.name}'",
        )

    # Remove template file from disk
    if template.file_path and os.path.exists(template.file_path):
        try:
            os.remove(template.file_path)
        except OSError:
            pass

    template_name = template.name
    db.delete(template)
    db.commit()

    return {"message": f"Template '{template_name}' deleted successfully", "id": template_id}


# ---------------------------------------------------------------------------
# Template Preview & Layout Positioning
# ---------------------------------------------------------------------------

@router.get(
    "/templates/{template_id}/background",
    summary="Get background image for a template",
)
def get_template_background(template_id: str, db: Session = Depends(get_db)):
    """Return the raw image for a template to render on the live preview canvas."""
    template = db.query(Template).filter(
        (Template.id == template_id) | (Template.name == template_id)
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # If user-uploaded file exists
    if template.file_path and os.path.exists(template.file_path):
        ext = template.file_path.lower().split(".")[-1]
        if ext in ("png", "jpg", "jpeg"):
            media = "image/png" if ext == "png" else "image/jpeg"
            return FileResponse(template.file_path, media_type=media)
        elif ext == "pdf":
            try:
                import pypdf
                r = pypdf.PdfReader(template.file_path)
                if r.pages and len(r.pages[0].images) > 0:
                    img_data = r.pages[0].images[0].data
                    return Response(content=img_data, media_type="image/png")
            except Exception:
                pass

    # Built-in or fallback preview
    builtin_map = {
        "classic": os.path.abspath("outputs/certificate_classic.png"),
        "modern": os.path.abspath("outputs/certificate_modern.png"),
        "elegant": os.path.abspath("outputs/certificate_elegant.png"),
    }
    fallback_path = builtin_map.get(template.name)
    if fallback_path and os.path.exists(fallback_path):
        return FileResponse(fallback_path, media_type="image/png")

    # If custom template has outputs/template2.png as fallback
    if os.path.exists("outputs/template2.png"):
        return FileResponse(os.path.abspath("outputs/template2.png"), media_type="image/png")

    # Dynamic fallback rendering if image file does not exist on disk
    try:
        from PIL import Image, ImageDraw
        bg_col = "#FFF8E7" if template.name == "classic" else ("#1B2A4A" if template.name == "elegant" else "#FFFFFF")
        border_col = "#C8A951" if template.name in ("classic", "elegant") else "#2E86AB"
        img = Image.new("RGB", (880, 680), bg_col)
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 20, 860, 660], outline=border_col, width=4)
        draw.rectangle([35, 35, 845, 645], outline=border_col, width=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")
    except Exception:
        raise HTTPException(status_code=404, detail="Background preview image not available")


@router.put(
    "/templates/{template_id}/layout",
    response_model=TemplateResponse,
    summary="Update layout coordinates for a template",
)
def update_template_layout(
    template_id: str,
    layout: TemplateLayoutUpdate,
    db: Session = Depends(get_db),
):
    """Save calibrated layout coordinates and field visibility for a template."""
    template = db.query(Template).filter(
        (Template.id == template_id) | (Template.name == template_id)
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    template.name_x_ratio = layout.name_x_ratio
    template.name_y_ratio = layout.name_y_ratio
    template.course_x_ratio = layout.course_x_ratio
    template.course_y_ratio = layout.course_y_ratio
    template.date_x_ratio = layout.date_x_ratio
    template.date_y_ratio = layout.date_y_ratio
    template.show_course = 1 if layout.show_course else 0
    template.show_date = 1 if layout.show_date else 0
    if layout.name_font is not None:
        template.name_font = layout.name_font
    if layout.name_size is not None:
        template.name_size = layout.name_size
    if layout.name_color is not None:
        template.name_color = layout.name_color
    if layout.course_font is not None:
        template.course_font = layout.course_font
    if layout.course_size is not None:
        template.course_size = layout.course_size
    if layout.course_color is not None:
        template.course_color = layout.course_color
    if layout.date_font is not None:
        template.date_font = layout.date_font
    if layout.date_size is not None:
        template.date_size = layout.date_size
    if layout.date_color is not None:
        template.date_color = layout.date_color

    if not template.is_builtin:
        template.overlay_mode = "preprinted"

    db.commit()
    db.refresh(template)
    return TemplateResponse.model_validate(template)


@router.websocket("/ws/preview")
async def websocket_preview_endpoint(websocket: WebSocket, db: Session = Depends(get_db)):
    """WebSocket endpoint for real-time live certificate positioning and layout updates."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action", "preview")

            if action == "ping":
                await websocket.send_json({"action": "pong"})
                continue

            template_id = data.get("template_id")
            name_x = float(data.get("name_x", 0.5))
            name_y = float(data.get("name_y", 0.515))
            course_x = float(data["course_x"]) if data.get("course_x") is not None else None
            course_y = float(data["course_y"]) if data.get("course_y") is not None else None
            date_x = float(data["date_x"]) if data.get("date_x") is not None else None
            date_y = float(data["date_y"]) if data.get("date_y") is not None else None
            show_course = bool(data.get("show_course", True))
            show_date = bool(data.get("show_date", True))

            name_font = data.get("name_font")
            name_size = float(data["name_size"]) if data.get("name_size") is not None else None
            name_color = data.get("name_color")
            course_font = data.get("course_font")
            course_size = float(data["course_size"]) if data.get("course_size") is not None else None
            course_color = data.get("course_color")
            date_font = data.get("date_font")
            date_size = float(data["date_size"]) if data.get("date_size") is not None else None
            date_color = data.get("date_color")

            if action == "save_coords":
                tmpl = db.query(Template).filter(
                    (Template.id == template_id) | (Template.name == template_id)
                ).first()
                if tmpl:
                    tmpl.name_x_ratio = name_x
                    tmpl.name_y_ratio = name_y
                    tmpl.course_x_ratio = course_x
                    tmpl.course_y_ratio = course_y
                    tmpl.date_x_ratio = date_x
                    tmpl.date_y_ratio = date_y
                    tmpl.show_course = 1 if show_course else 0
                    tmpl.show_date = 1 if show_date else 0
                    if name_font is not None:
                        tmpl.name_font = name_font
                    if name_size is not None:
                        tmpl.name_size = name_size
                    if name_color is not None:
                        tmpl.name_color = name_color
                    if course_font is not None:
                        tmpl.course_font = course_font
                    if course_size is not None:
                        tmpl.course_size = course_size
                    if course_color is not None:
                        tmpl.course_color = course_color
                    if date_font is not None:
                        tmpl.date_font = date_font
                    if date_size is not None:
                        tmpl.date_size = date_size
                    if date_color is not None:
                        tmpl.date_color = date_color

                    if not tmpl.is_builtin:
                        tmpl.overlay_mode = "preprinted"
                    db.commit()
                    await websocket.send_json({
                        "action": "coords_saved",
                        "status": "ok",
                        "template_id": tmpl.id,
                        "template_name": tmpl.name,
                        "message": f"Layout & styling saved successfully for '{tmpl.name}'!",
                    })
                else:
                    await websocket.send_json({
                        "action": "error",
                        "detail": f"Template '{template_id}' not found",
                    })
            else:
                await websocket.send_json({
                    "action": "coords_updated",
                    "status": "ok",
                    "coords": {
                        "name_x": round(name_x, 3),
                        "name_y": round(name_y, 3),
                        "course_x": round(course_x, 3) if course_x is not None else None,
                        "course_y": round(course_y, 3) if course_y is not None else None,
                        "date_x": round(date_x, 3) if date_x is not None else None,
                        "date_y": round(date_y, 3) if date_y is not None else None,
                        "show_course": show_course,
                        "show_date": show_date,
                        "name_font": name_font,
                        "name_size": name_size,
                        "name_color": name_color,
                        "course_font": course_font,
                        "course_size": course_size,
                        "course_color": course_color,
                        "date_font": date_font,
                        "date_size": date_size,
                        "date_color": date_color,
                    },
                })
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"action": "error", "detail": str(e)})
        except Exception:
            pass

