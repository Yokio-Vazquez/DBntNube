import os
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()


def build_database_url(user_var: str, password_var: str, host_var: str, port_var: str, database_var: str) -> URL:
    return URL.create(
        drivername="postgresql+psycopg",
        username=os.environ[user_var],
        password=os.environ[password_var],
        host=os.environ[host_var],
        port=int(os.environ[port_var]),
        database=os.environ[database_var],
    )


WRITER_DATABASE_URL = build_database_url(
    "DB_USER_WRITER",
    "DB_PASSWORD_WRITER",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
)

READER_DATABASE_URL = build_database_url(
    "DB_USER_READER",
    "DB_PASSWORD_READER",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
)

MIGRATOR_DATABASE_URL = build_database_url(
    "DB_USER_MIGRATOR",
    "DB_PASSWORD_MIGRATOR",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
)

# Conexión administrativa para Alembic (antes de crear los roles)
ADMIN_DATABASE_URL = URL.create(
    drivername="postgresql+psycopg",
    username=os.environ.get("POSTGRES_USER", "cdrl_dev"),
    password=os.environ.get("POSTGRES_PASSWORD", "replace-me-bootstrap"),
    host=os.environ.get("DB_HOST", "localhost"),
    port=int(os.environ.get("DB_PORT", "5432")),
    database=os.environ.get("POSTGRES_DB", "cdrl"),
)

writer_engine = create_engine(WRITER_DATABASE_URL)
WriterSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=writer_engine)

reader_engine = create_engine(READER_DATABASE_URL)
ReaderSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=reader_engine)

migrator_engine = create_engine(MIGRATOR_DATABASE_URL)
MigratorSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=migrator_engine)

Base = declarative_base()

def get_db_writer():
    db = WriterSessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_db_reader():
    db = ReaderSessionLocal()
    try:
        yield db
    finally:
        db.close()
