"""SQLAlchemy declarative base for server-owned metadata."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all server metadata tables."""
