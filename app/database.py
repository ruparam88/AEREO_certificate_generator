"""Database engine and session management.

Uses SQLAlchemy with SQLite. The `check_same_thread=False` argument is
required because FastAPI serves requests across multiple threads, but
SQLite's default mode restricts connections to the creating thread.

For production, swap the DATABASE_URL to PostgreSQL — no other changes needed.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite-specific
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that provides a database session per request.

    Yields a session and ensures it is closed after the request completes,
    even if an exception occurs.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
