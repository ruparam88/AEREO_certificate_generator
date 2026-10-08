"""Job processing service.

Handles the business logic for creating and processing bulk certificate
generation jobs. The key design decision here is using FastAPI's
BackgroundTasks for async processing:

    Why BackgroundTasks instead of Celery?
    - No extra infrastructure (Redis, RabbitMQ) required.
    - Appropriate for the scope of this project.
    - Easy to understand and debug.
    - Can be swapped to Celery later without changing the API contract.

    Why a separate DB session in the background task?
    - The request's DB session is closed after the response is sent.
    - Background tasks run after the response, so they need their own session.
"""

import os
from datetime import datetime
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Job, Certificate, Template, JobStatus, CertificateStatus
from app.schemas import JobCreate
from app.services.certificate_generator import generate_certificate
from app.config import settings


def create_job(db: Session, job_data: JobCreate) -> Job:
    """Create a new job and its certificate records in the database.

    This function is called synchronously during the API request. It:
    1. Validates the template exists.
    2. Creates the Job record.
    3. Creates a Certificate record for each recipient.
    4. Returns the Job so the router can enqueue background processing.

    Args:
        db: Active database session from the request.
        job_data: Validated request body with recipients and template_id.

    Returns:
        The newly created Job ORM object.

    Raises:
        ValueError: If the specified template_id doesn't exist.
    """
    # Verify the template exists
    template = db.query(Template).filter(Template.id == job_data.template_id).first()
    if not template:
        raise ValueError(f"Template '{job_data.template_id}' not found")

    # Create the job
    job = Job(
        template_id=job_data.template_id,
        status=JobStatus.PENDING,
        total_recipients=len(job_data.recipients),
    )
    db.add(job)
    db.flush()  # Get the job.id without committing

    # Create a certificate record for each recipient
    for recipient in job_data.recipients:
        certificate = Certificate(
            job_id=job.id,
            recipient_name=recipient.name,
            recipient_email=recipient.email,
            course_name=recipient.course_name,
            date=recipient.date,
            status=CertificateStatus.PENDING,
        )
        db.add(certificate)

    db.commit()
    db.refresh(job)
    return job


def process_job(job_id: str) -> None:
    """Background task: generate all certificates for a job.

    This function runs AFTER the API response is sent. It creates its
    own database session because the request session is already closed.

    Processing strategy:
    - Each certificate is generated independently inside a try/except.
    - If one fails, the error is recorded and processing continues.
    - The job completes even if some certificates fail.
    - Counts are updated after all processing is done.

    Args:
        job_id: The UUID of the job to process.
    """
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return

        # Transition to processing
        job.status = JobStatus.PROCESSING
        db.commit()

        # Determine template style, custom path, and overlay mode
        template = db.query(Template).filter(Template.id == job.template_id).first()
        template_style = template.name if template and template.is_builtin else "classic"
        custom_template_path = (
            template.file_path
            if template and not template.is_builtin and template.file_path
            else None
        )
        overlay_mode = getattr(template, "overlay_mode", "full") or ("preprinted" if custom_template_path else "full")
        name_y_ratio = getattr(template, "name_y_ratio", 0.515) or 0.515
        course_y_ratio = getattr(template, "course_y_ratio", None)
        course_x_ratio = getattr(template, "course_x_ratio", None)
        date_y_ratio = getattr(template, "date_y_ratio", None)
        date_x_ratio = getattr(template, "date_x_ratio", None)
        show_course = bool(getattr(template, "show_course", 1))
        show_date = bool(getattr(template, "show_date", 1))
        font_family = getattr(template, "font_family", "sans") or "sans"
        primary_color = getattr(template, "primary_color", None)
        accent_color = getattr(template, "accent_color", None)

        # Process each certificate independently
        certificates = (
            db.query(Certificate)
            .filter(Certificate.job_id == job_id)
            .all()
        )

        success_count = 0
        fail_count = 0

        for cert in certificates:
            try:
                file_path = generate_certificate(
                    recipient_name=cert.recipient_name,
                    course_name=cert.course_name,
                    date=cert.date,
                    certificate_id=cert.id,
                    output_dir=settings.certificates_dir,
                    template_style=template_style,
                    custom_template_path=custom_template_path,
                    overlay_mode=overlay_mode,
                    name_y_ratio=name_y_ratio,
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
                cert.status = CertificateStatus.SUCCESS
                cert.file_path = file_path
                success_count += 1
            except Exception as e:
                cert.status = CertificateStatus.FAILED
                cert.error_message = str(e)
                fail_count += 1

            # Commit after each certificate so progress is visible
            db.commit()

        # Finalize job
        job.successful_count = success_count
        job.failed_count = fail_count
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.utcnow()
        db.commit()

    finally:
        db.close()


def seed_default_templates(db: Session) -> None:
    """Insert built-in templates if they don't already exist.

    Called once at application startup. Uses the template name as the
    primary key for built-in templates so they're stable across restarts.
    """
    builtin_templates = [
        {
            "id": "classic",
            "name": "classic",
            "description": "Traditional gold-bordered certificate with a cream background",
            "is_builtin": 1,
            "overlay_mode": "full",
            "name_y_ratio": 0.515,
            "font_family": "serif",
            "primary_color": "#1B2A4A",
            "accent_color": "#C8A951",
        },
        {
            "id": "modern",
            "name": "modern",
            "description": "Clean, minimalist design with blue geometric accents",
            "is_builtin": 1,
            "overlay_mode": "full",
            "name_y_ratio": 0.515,
            "font_family": "sans",
            "primary_color": "#0F172A",
            "accent_color": "#2E86AB",
        },
        {
            "id": "elegant",
            "name": "elegant",
            "description": "Premium dark navy design with gold highlights",
            "is_builtin": 1,
            "overlay_mode": "full",
            "name_y_ratio": 0.515,
            "font_family": "elegant",
            "primary_color": "#FFFFFF",
            "accent_color": "#E5C378",
        },
    ]

    for tmpl_data in builtin_templates:
        exists = db.query(Template).filter(Template.id == tmpl_data["id"]).first()
        if not exists:
            db.add(Template(**tmpl_data))
        else:
            # Refresh built-in template typography and styling
            exists.font_family = tmpl_data["font_family"]
            exists.primary_color = tmpl_data["primary_color"]
            exists.accent_color = tmpl_data["accent_color"]

    db.commit()
