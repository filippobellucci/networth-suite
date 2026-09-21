from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import DATABASE_URL

is_sqlite = DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}

# NullPool for SQLite: a connection is opened per session and closed with it,
# instead of being borrowed from a pool that can run out.
#
# SQLAlchemy's default QueuePool caps this engine at 5 connections plus 10
# overflow -- 15 concurrent sessions, and the 16th waits 30 seconds and then
# fails outright. A request holds its connection for as long as it holds its
# session, which here means for the whole of the work it does, price lookups
# included: /history values the portfolio once per tracked day, each with a
# price and an FX call, and keeps its connection the entire time. So the
# ceiling is not reached by "lots of traffic" -- a handful of slow requests
# is enough, and this app's own gateway fans the dashboard out into one
# concurrent request per portfolio plus the combined history and totals.
# Past the ceiling the failure is the bad kind: a 30-second hang, then
# QueuePool's TimeoutError as a 500, which the gateway reports as the module
# being unreachable. Measured at 20 concurrent mixed read/write requests,
# 52 of 60 failed that way.
#
# Opening a SQLite connection is a local file handle, not a network
# handshake, so there is nothing worth pooling here -- this is what
# SQLAlchemy itself used to do for file-backed SQLite. A non-SQLite
# DATABASE_URL (where pooling does matter) keeps the default pool.
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    **({"poolclass": NullPool} if is_sqlite else {}),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
