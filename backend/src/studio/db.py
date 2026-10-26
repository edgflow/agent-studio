"""Database engine and the per-request session."""

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from studio.config import get_settings


class Base(DeclarativeBase):
    # Every datetime column is TIMESTAMPTZ: values are stored and compared in UTC.
    type_annotation_map = {datetime: DateTime(timezone=True)}


engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """One session per request: committed if the handler succeeds, rolled back if it raises."""
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise


# scope="function": commit when the handler returns, *before* the response is
# sent. FastAPI's default runs this cleanup after the response (and after
# background tasks), so a client could see 200 OK for a change not yet saved.
Db = Annotated[Session, Depends(get_db, scope="function")]
