"""SQLAlchemy ORM models.

Defines the database schema for the certificate generation system:
- Job: A bulk generation request containing one or more recipients.
- Certificate: An individual certificate tied to a specific job and recipient.
- Template: Available certificate templates (both built-in and user-uploaded).

Relationships:
    Job 1──* Certificate  (one job produces many certificates)
    Template 1──* Job      (one template is used per job)
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, Float
from sqlalchemy.orm import relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Constants for status values — avoids typos from using raw strings
# ---------------------------------------------------------------------------

class JobStatus:
    """Allowed status values for a Job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class CertificateStatus:
    """Allowed status values for a Certificate."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

def _generate_uuid() -> str:
    """Generate a new UUID4 string for use as a primary key."""
    return str(uuid4())


class Template(Base):
    """A certificate template.

    Built-in templates are seeded on startup. Users can also upload custom
    templates via the API. The `file_path` points to the template image/PDF
    on disk; `is_builtin` distinguishes system templates from user uploads.
    `overlay_mode` determines whether to draw full certificate headers or
    only recipient name and details onto pre-designed templates.
    """
    __tablename__ = "templates"

    id = Column(String, primary_key=True, default=_generate_uuid)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(300), nullable=True)
    file_path = Column(String(500), nullable=True)  # None for code-generated templates
    is_builtin = Column(Integer, default=1)  # 1 = built-in, 0 = user-uploaded
    overlay_mode = Column(String(50), default="full")  # "full" or "preprinted"
    name_y_ratio = Column(Float, default=0.515)  # Y position of name from bottom (fraction)
    name_x_ratio = Column(Float, default=0.5)    # X position of name from left (fraction)
    course_y_ratio = Column(Float, nullable=True)  # Y position of course name from bottom
    course_x_ratio = Column(Float, nullable=True)  # X position of course name from left
    date_y_ratio = Column(Float, nullable=True)  # Y position of date from bottom
    date_x_ratio = Column(Float, nullable=True)  # X position of date from left
    show_course = Column(Integer, default=1)  # 1 = show course, 0 = hide
    show_date = Column(Integer, default=1)  # 1 = show date, 0 = hide
    font_family = Column(String(50), default="sans")  # "sans", "serif", "elegant"
    primary_color = Column(String(20), default="#1E293B")  # Hex color e.g. "#0A001D"
    accent_color = Column(String(20), default="#2E86AB")  # Hex color e.g. "#609AAD"
    created_at = Column(DateTime, default=datetime.utcnow)

    jobs = relationship("Job", back_populates="template", cascade="all, delete-orphan")


class Job(Base):
    """A bulk certificate generation request.

    When a client submits a list of recipients, a Job is created to track
    the overall progress. The job transitions through statuses:
        pending → processing → completed

    If every certificate fails, the job status is still 'completed'
    (not 'failed'), because the job itself ran to completion. The counts
    tell the client what succeeded and what didn't.
    """
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=_generate_uuid)
    template_id = Column(String, ForeignKey("templates.id"), nullable=False)
    status = Column(String(20), default=JobStatus.PENDING)
    total_recipients = Column(Integer, nullable=False)
    successful_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    template = relationship("Template", back_populates="jobs")
    certificates = relationship("Certificate", back_populates="job", cascade="all, delete-orphan")


class Certificate(Base):
    """An individual certificate within a job.

    Each recipient in a job gets one Certificate record. The status tracks
    whether generation succeeded or failed independently of other
    certificates in the same job — one failure does not block the rest.

    Fields:
        recipient_name: The name printed on the certificate.
        recipient_email: Optional contact email (not printed, for records).
        course_name: The course/event name printed on the certificate.
        date: The date printed on the certificate (ISO format string).
        file_path: Path to the generated PDF on disk (set after success).
        error_message: Human-readable error (set after failure).
    """
    __tablename__ = "certificates"

    id = Column(String, primary_key=True, default=_generate_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    recipient_name = Column(String(200), nullable=False)
    recipient_email = Column(String(320), nullable=True)
    course_name = Column(String(300), nullable=False)
    date = Column(String(10), nullable=False)  # YYYY-MM-DD format
    status = Column(String(20), default=CertificateStatus.PENDING)
    error_message = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    job = relationship("Job", back_populates="certificates")
