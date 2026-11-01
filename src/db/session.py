import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def database(url=None):
    url = url or os.environ.get("DATABASE_URL")
    if not url or not url.startswith(("postgresql://", "postgresql+psycopg2://")):
        raise ValueError("DATABASE_URL must identify PostgreSQL; no file persistence fallback")
    engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    return engine, sessionmaker(engine, expire_on_commit=False)
