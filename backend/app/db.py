"""SQLite schema and engine (spec §6.2). SQLAlchemy Core, shared by api and worker."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    insert,
    select,
    text,
)
from sqlalchemy.engine import Engine

SCHEMA_VERSION = 1

metadata = MetaData()

songs = Table(
    "songs",
    metadata,
    Column("id", String, primary_key=True),
    Column("title", Text, nullable=False),
    Column("artist", Text),
    Column("album", Text),
    Column("duration_s", Float),
    Column("source_type", String, nullable=False),
    Column("source_url", Text),
    Column("source_key", Text, unique=True),
    Column("original_filename", Text),
    Column("original_ext", String, nullable=False),
    Column("stem_mode", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("favorite", Integer, nullable=False, server_default="0"),
    Column("notes", Text, nullable=False, server_default=""),
    Column("has_cover", Integer, nullable=False, server_default="0"),
    Column("metadata_edited", Integer, nullable=False, server_default="0"),
    Column("bpm", Float),
    Column("key_label", Text),
    Column("analysis_status", String, nullable=False, server_default="none"),
    Column("player_state", Text, nullable=False, server_default="{}"),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    CheckConstraint("stem_mode IN (2,4,6)"),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("song_id", String, ForeignKey("songs.id", ondelete="CASCADE"), nullable=False),
    Column("stem_mode", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("step", String),
    Column("step_detail", String),
    Column("step_index", Integer, nullable=False, server_default="0"),
    Column("step_count", Integer, nullable=False, server_default="0"),
    Column("step_progress", Integer, nullable=False, server_default="0"),
    Column("error_code", String),
    Column("error_detail", Text),
    Column("cancel_requested", Integer, nullable=False, server_default="0"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("created_at", String, nullable=False),
    Column("started_at", String),
    Column("finished_at", String),
)

Index(
    "jobs_one_active",
    jobs.c.song_id,
    unique=True,
    sqlite_where=text("status IN ('queued','running')"),
)

tags = Table(
    "tags",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text(collation="NOCASE"), nullable=False, unique=True),
)

song_tags = Table(
    "song_tags",
    metadata,
    Column("song_id", String, ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

markers = Table(
    "markers",
    metadata,
    Column("id", String, primary_key=True),
    Column("song_id", String, ForeignKey("songs.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String, nullable=False),
    Column("name", Text, nullable=False),
    Column("start_s", Float, nullable=False),
    Column("end_s", Float),
    Column("created_at", String, nullable=False),
)

settings = Table(
    "settings",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", Text, nullable=False),
)

schema_version = Table(
    "schema_version",
    metadata,
    Column("version", Integer, primary_key=True),
)

SETTINGS_DEFAULTS = {"language": None, "default_stem_mode": 4, "metronome_volume": 70}
ACTIVE_JOB_STATUSES = ("queued", "running")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def make_engine(db_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    metadata.create_all(engine)
    with engine.begin() as conn:
        if conn.execute(select(schema_version.c.version)).first() is None:
            conn.execute(insert(schema_version).values(version=SCHEMA_VERSION))
    return engine


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        from .config import get_paths

        _engine = make_engine(get_paths().db)
    return _engine


def set_engine(engine: Engine | None) -> None:
    global _engine
    _engine = engine


def get_setting(conn, key: str):  # noqa: ANN001
    row = conn.execute(select(settings.c.value).where(settings.c.key == key)).first()
    if row is None:
        return SETTINGS_DEFAULTS.get(key)
    return json.loads(row.value)


def set_setting(conn, key: str, value) -> None:  # noqa: ANN001
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    stmt = sqlite_insert(settings).values(key=key, value=json.dumps(value))
    stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value})
    conn.execute(stmt)
