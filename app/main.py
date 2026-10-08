"""FastAPI application entry point.

This module creates and configures the FastAPI application instance.
On startup, it:
    1. Creates all database tables (if they don't exist).
    2. Seeds default certificate templates.
    3. Ensures the output directory exists.

Run with: uvicorn app.main:app --reload
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import engine, Base, SessionLocal
from app.routers import jobs
from app.services.job_service import seed_default_templates
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager.

    Runs setup code before the app starts accepting requests, and
    cleanup code when it shuts down.

    Using lifespan instead of @app.on_event("startup") because the
    latter is deprecated in newer FastAPI versions.
    """
    # --- Startup ---
    # Create database tables
    Base.metadata.create_all(bind=engine)

    # Ensure database schema has new columns if migrating from earlier schema
    try:
        with engine.connect() as conn:
            cursor = conn.connection.cursor()
            cursor.execute("PRAGMA table_info(templates)")
            cols = [row[1] for row in cursor.fetchall()]
            if cols and "overlay_mode" not in cols:
                cursor.execute("ALTER TABLE templates ADD COLUMN overlay_mode VARCHAR(50) DEFAULT 'full'")
            if cols and "name_y_ratio" not in cols:
                cursor.execute("ALTER TABLE templates ADD COLUMN name_y_ratio FLOAT DEFAULT 0.515")
            if cols and "name_x_ratio" not in cols:
                cursor.execute("ALTER TABLE templates ADD COLUMN name_x_ratio FLOAT DEFAULT 0.5")
            if cols and "course_y_ratio" not in cols:
                cursor.execute("ALTER TABLE templates ADD COLUMN course_y_ratio FLOAT")
            if cols and "course_x_ratio" not in cols:
                cursor.execute("ALTER TABLE templates ADD COLUMN course_x_ratio FLOAT")
            if cols and "date_y_ratio" not in cols:
                cursor.execute("ALTER TABLE templates ADD COLUMN date_y_ratio FLOAT")
            if cols and "date_x_ratio" not in cols:
                cursor.execute("ALTER TABLE templates ADD COLUMN date_x_ratio FLOAT")
            if cols and "show_course" not in cols:
                cursor.execute("ALTER TABLE templates ADD COLUMN show_course INTEGER DEFAULT 1")
            if cols and "show_date" not in cols:
                cursor.execute("ALTER TABLE templates ADD COLUMN show_date INTEGER DEFAULT 1")
            if cols and "font_family" not in cols:
                cursor.execute("ALTER TABLE templates ADD COLUMN font_family VARCHAR(50) DEFAULT 'sans'")
            if cols and "primary_color" not in cols:
                cursor.execute("ALTER TABLE templates ADD COLUMN primary_color VARCHAR(20) DEFAULT '#1E293B'")
            if cols and "accent_color" not in cols:
                cursor.execute("ALTER TABLE templates ADD COLUMN accent_color VARCHAR(20) DEFAULT '#2E86AB'")
            conn.connection.commit()
    except Exception:
        pass

    # Seed built-in templates
    db = SessionLocal()
    try:
        seed_default_templates(db)
    finally:
        db.close()

    # Ensure output directories exist
    os.makedirs(settings.certificates_dir, exist_ok=True)
    os.makedirs(settings.uploaded_templates_dir, exist_ok=True)

    yield  # App is running and accepting requests

    # --- Shutdown ---
    # Nothing to clean up for now


app = FastAPI(
    title="Bulk Certificate Generator",
    description=(
        "API for generating certificates in bulk for event/course participants. "
        "Submit a list of recipients, choose a template, and retrieve generated "
        "PDF certificates individually or as a ZIP archive."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Register routes under /api/v1 prefix
app.include_router(jobs.router, prefix="/api/v1")


@app.get("/", summary="Web UI for Bulk Certificate Generator", include_in_schema=False)
def serve_index():
    """Serve the single-page application for browser testing and demo."""
    from fastapi.responses import FileResponse
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    return FileResponse(index_path, media_type="text/html")
