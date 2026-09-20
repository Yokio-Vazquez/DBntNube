import os
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


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

MIGRATOR_DATABASE_URL = build_database_url(
    "DB_USER_MIGRATOR",
    "DB_PASSWORD_MIGRATOR",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
)

DATABASE_URL = WRITER_DATABASE_URL
SQLALCHEMY_DATABASE_URL = DATABASE_URL.render_as_string(hide_password=False)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
