"""Pydantic schemas for request validation and response serialization.

This module defines the data contracts between the API and its clients.
FastAPI uses these schemas to:
  1. Validate incoming request bodies (return 422 on invalid data).
  2. Serialize database objects into clean JSON responses.
  3. Generate accurate OpenAPI/Swagger documentation.

Naming convention:
  - *Create  → request body for creating a resource
  - *Response → response body returned to the client
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, EmailStr, field_validator, ConfigDict


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class RecipientCreate(BaseModel):
    """A single recipient in a bulk certificate request.

    Attributes:
        name: Full name of the recipient (printed on the certificate).
        email: Optional email address (stored for records, not printed).
        course_name: Name of the course or event.
        date: Date to print on the certificate (YYYY-MM-DD format).
    """
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Recipient's full name",
        examples=["Jane Doe"],
    )
    email: Optional[EmailStr] = Field(
        default=None,
        description="Recipient's email (optional, for records only)",
        examples=["jane@example.com"],
    )
    course_name: str = Field(
        ...,
        min_length=1,
        max_length=300,
        description="Course or event name",
        examples=["Advanced Python Workshop"],
    )
    date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Certificate date in YYYY-MM-DD format",
        examples=["2024-12-15"],
    )

    @field_validator("date")
    @classmethod
    def validate_date_is_real(cls, v: str) -> str:
        """Ensure the date string represents a valid calendar date.

        The regex pattern ensures format, but '2024-02-31' would pass regex
        yet isn't a real date. This validator catches that.
        """
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"'{v}' is not a valid calendar date")
        return v


class JobCreate(BaseModel):
    """Request body for creating a bulk certificate generation job.

    Attributes:
        recipients: List of recipients to generate certificates for.
        template_id: ID of the template to use (defaults to 'classic').
    """
    recipients: list[RecipientCreate] = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="List of recipients (1–10,000)",
    )
    template_id: str = Field(
        default="classic",
        description="Template ID to use. Options: 'classic', 'modern', 'elegant', or a custom template ID.",
        examples=["classic"],
    )


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------

class TemplateResponse(BaseModel):
    """Response schema for a certificate template."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    is_builtin: bool
    overlay_mode: Optional[str] = "full"
    name_y_ratio: Optional[float] = 0.515
    name_x_ratio: Optional[float] = 0.5
    course_y_ratio: Optional[float] = None
    course_x_ratio: Optional[float] = None
    date_y_ratio: Optional[float] = None
    date_x_ratio: Optional[float] = None
    show_course: Optional[bool] = True
    show_date: Optional[bool] = True
    font_family: Optional[str] = "sans"
    primary_color: Optional[str] = "#1E293B"
    accent_color: Optional[str] = "#2E86AB"


class TemplateLayoutUpdate(BaseModel):
    """Schema for updating template layout coordinates and visibility."""
    name_x_ratio: Optional[float] = 0.5
    name_y_ratio: Optional[float] = 0.515
    course_x_ratio: Optional[float] = None
    course_y_ratio: Optional[float] = None
    date_x_ratio: Optional[float] = None
    date_y_ratio: Optional[float] = None
    show_course: Optional[bool] = True
    show_date: Optional[bool] = True


class CertificateResponse(BaseModel):
    """Response schema for an individual certificate."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    recipient_name: str
    recipient_email: Optional[str]
    course_name: str
    date: str
    status: str
    error_message: Optional[str]
    download_url: Optional[str] = None  # Populated in the router


class JobResponse(BaseModel):
    """Summary response for a job (without certificate details).

    Provides enough information to check progress at a glance:
    - status: overall job status
    - total/successful/failed counts: track generation progress
    """
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    template_id: str
    total_recipients: int
    successful_count: int
    failed_count: int
    created_at: datetime
    completed_at: Optional[datetime]


class JobDetailResponse(JobResponse):
    """Detailed job response including all certificate records."""
    model_config = ConfigDict(from_attributes=True)

    certificates: list[CertificateResponse]
