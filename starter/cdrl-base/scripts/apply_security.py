#!/usr/bin/env python
"""Aplica el SQL de RBAC al contenedor PostgreSQL de forma portable (Windows/Linux/Mac)."""
import subprocess
import sys
from pathlib import Path

sql = Path("db/migrations/002_roles_and_privileges.sql").read_bytes()

result = subprocess.run(
    [
        "docker", "compose", "exec", "-T", "postgres",
        "sh", "-c",
        (
            "psql --username $POSTGRES_USER --dbname $POSTGRES_DB"
            " --set=migrator_password=$CDRL_MIGRATOR_PASSWORD"
            " --set=writer_password=$CDRL_WRITER_PASSWORD"
            " --set=reader_password=$CDRL_READER_PASSWORD"
            " --set=operator_password=$CDRL_OPERATOR_PASSWORD"
        ),
    ],
    input=sql,
)
sys.exit(result.returncode)
