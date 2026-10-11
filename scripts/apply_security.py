#!/usr/bin/env python
"""Aplica el SQL de RBAC al contenedor PostgreSQL de forma portable (Windows/Linux/Mac)."""
import subprocess
import sys
from pathlib import Path

sql = b"\n".join(
    Path(path).read_bytes()
    for path in (
        "db/migrations/002_roles_and_privileges.sql",
        "db/migrations/003_enforce_role_privileges.sql",
    )
)

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
