from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import DATABASE_URL

is_sqlite = DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}

# NullPool for SQLite: a connection is opened per session and closed with it,
# instead of being borrowed from a pool that can run out.
#
# A request holds its connection for all of its work, price lookups
# included, so a handful of slow requests (the dashboard fans out one per
# portfolio) exhausts QueuePool's 15 connections. Opening a SQLite connection
# is just a file handle, so there is nothing worth pooling. A non-SQLite
# DATABASE_URL keeps the default pool.
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
