import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Configuracion de base de datos desde entorno
POSTGRES_USER = os.getenv("POSTGRES_USER", "cdrl_dev")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "cdrl_dev_only")
POSTGRES_DB = os.getenv("POSTGRES_DB", "cdrl")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

SQLALCHEMY_DATABASE_URL = f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
