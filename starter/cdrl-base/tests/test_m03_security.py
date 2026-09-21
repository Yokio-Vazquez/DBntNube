import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError, OperationalError

# Reusamos la lógica de conexión de la API pero probando credenciales específicas
def build_url(user, password):
    return f"postgresql+psycopg://{user}:{password}@localhost:5432/cdrl"

def test_reader_cannot_insert():
    # Conectamos como cdrl_reader
    url = build_url(os.environ.get("DB_USER_READER", "cdrl_reader"), os.environ.get("DB_PASSWORD_READER", "replace-me-reader"))
    engine = create_engine(url)
    
    with engine.connect() as conn:
        with pytest.raises(ProgrammingError) as exc_info:
            conn.execute(text("INSERT INTO games (title, genre, classification, description, release_date) VALUES ('Test', 'RPG', 'E', 'Test', '2023-01-01')"))
            conn.commit()
        # Verificamos que el error es por permisos insuficientes
        assert "permission denied" in str(exc_info.value).lower()

def test_writer_cannot_drop_table():
    # Conectamos como cdrl_writer
    url = build_url(os.environ.get("DB_USER_WRITER", "cdrl_writer"), os.environ.get("DB_PASSWORD_WRITER", "replace-me-writer"))
    engine = create_engine(url)
    
    with engine.connect() as conn:
        with pytest.raises(ProgrammingError) as exc_info:
            conn.execute(text("DROP TABLE games CASCADE"))
            conn.commit()
        # Verificamos que el error es por permisos denegados o propietario
        assert "must be owner of table" in str(exc_info.value).lower() or "permission denied" in str(exc_info.value).lower()

def test_invalid_credentials_rejected():
    # Conectamos con credenciales falsas
    url = build_url("cdrl_reader", "contrasena_equivocada_falsa")
    engine = create_engine(url)
    
    with pytest.raises(OperationalError) as exc_info:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    
    # Debe ser error de autenticación fallida
    assert "password authentication failed" in str(exc_info.value).lower()
