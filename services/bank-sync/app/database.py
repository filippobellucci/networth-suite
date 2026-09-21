from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import DATABASE_URL

is_sqlite = DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}

# NullPool, for the same reason as core-networth's engine (see the fuller
# note there): a session here is held for as long as the work it covers, and
# a sync cycle's session stays open across every bank call it makes. There
# is no pool ceiling to run into this way, and opening a SQLite connection
# costs a file handle rather than a handshake.
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    **({"poolclass": NullPool} if is_sqlite else {}),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
