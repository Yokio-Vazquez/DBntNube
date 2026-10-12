import os
import pytest
from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import ProgrammingError, OperationalError

load_dotenv()

# Reusamos la lógica de conexión de la API pero probando credenciales específicas
def build_url(user, password):
    return URL.create(
        drivername="postgresql+psycopg",
        username=user,
        password=password,
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        database=os.environ["DB_NAME"],
    )

def test_reader_cannot_insert():
    # Conectamos como cdrl_reader
    url = build_url(os.environ["DB_USER_READER"], os.environ["DB_PASSWORD_READER"])
    engine = create_engine(url)
    
    with engine.connect() as conn:
        with pytest.raises(ProgrammingError) as exc_info:
            conn.execute(text("INSERT INTO games (title, genre, classification, description, release_date) VALUES ('Test', 'RPG', 'E', 'Test', '2023-01-01')"))
            conn.commit()
        # Verificamos que el error es por permisos insuficientes
        assert "permission denied" in str(exc_info.value).lower()

def test_writer_cannot_select_business_tables():
    url = build_url(os.environ["DB_USER_WRITER"], os.environ["DB_PASSWORD_WRITER"])
    engine = create_engine(url)

    with engine.connect() as conn:
        with pytest.raises(ProgrammingError) as exc_info:
            conn.execute(text("SELECT id FROM games LIMIT 1"))
        assert "permission denied" in str(exc_info.value).lower()

def test_writer_cannot_drop_table():
    # Conectamos como cdrl_writer
    url = build_url(os.environ["DB_USER_WRITER"], os.environ["DB_PASSWORD_WRITER"])
    engine = create_engine(url)
    
    with engine.connect() as conn:
        with pytest.raises(ProgrammingError) as exc_info:
            conn.execute(text("DROP TABLE games CASCADE"))
            conn.commit()
        # Verificamos que el error es por permisos denegados o propietario
        assert "must be owner of table" in str(exc_info.value).lower() or "permission denied" in str(exc_info.value).lower()

def test_invalid_credentials_rejected():
    # Conectamos con credenciales falsas
    url = build_url(os.environ["DB_USER_READER"], os.environ["DB_PASSWORD_INVALID_TEST"])
    engine = create_engine(url)
    
    with pytest.raises(OperationalError) as exc_info:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    
    # Debe ser error de autenticación fallida
    assert "password authentication failed" in str(exc_info.value).lower()
