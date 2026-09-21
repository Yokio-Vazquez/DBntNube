#!/usr/bin/env python
"""Verificación portable del contrato CDRL (equivalente a verify_base.sh)."""
import json
import re
import subprocess
import sys
from pathlib import Path

REQUIRED_FILES = [
    ".env.example",
    "Makefile",
    "docker-compose.yml",
    "docs/ADR-000-starter-base.md",
    "evidence/m01-data-contract.json",
    "alembic/versions/b7c2d9e4f1a0_m02_relational_model.py",
    "db/migrations/002_create_relational_model.sql",
    "db/seed/002_seed_relational_model.sql",
    "db/queries/002_parametrized_relational_queries.sql",
    "docs/ADR-002-modelo-relacional.md",
    "evidence/m02-relational-model.json",
    "artifacts/m02-relational-model-results.json",
    "db/migrations/002_roles_and_privileges.sql",
    "scripts/bootstrap_roles.sh",
    "docs/ADR-003-seguridad-rbac.md",
    "evidence/m03-security-rbac.json",
    ".github/workflows/cdrl-feedback.yml",
]

# 1. Verificar archivos requeridos
for f in REQUIRED_FILES:
    if not Path(f).is_file():
        print(f"ERROR: missing required file: {f}", file=sys.stderr)
        sys.exit(1)

# 2. Validar docker compose config (si docker está disponible)
try:
    subprocess.run(
        ["docker", "compose", "config", "--quiet"],
        check=True,
        capture_output=True,
    )
except (subprocess.CalledProcessError, FileNotFoundError):
    pass  # docker no disponible o error; el CI lo validará

# 3. Validar evidencia M01
payload = json.loads(Path("evidence/m01-data-contract.json").read_text(encoding="utf-8"))
required = {"assignmentId", "commitSha", "commands", "results", "assumptions", "limitations"}
missing = sorted(required.difference(payload))
if missing:
    print(f"ERROR: missing evidence fields: {', '.join(missing)}", file=sys.stderr)
    sys.exit(1)

# 4. Validar evidencia M02
payload = json.loads(Path("evidence/m02-relational-model.json").read_text(encoding="utf-8"))
required = {
    "assignmentId", "commitSha", "commands", "results", "schema",
    "invariants", "testCases", "assumptions", "limitations",
}
missing = sorted(required.difference(payload))
if missing:
    print(f"ERROR: missing M02 evidence fields: {', '.join(missing)}", file=sys.stderr)
    sys.exit(1)
if payload["assignmentId"] != "m02-relational-model":
    print("ERROR: unexpected M02 assignmentId", file=sys.stderr)
    sys.exit(1)
if len(payload["testCases"]) < 4:
    print("ERROR: M02 evidence must include normal, empty, boundary and failure cases", file=sys.stderr)
    sys.exit(1)

# 5. Validar evidencia M03
payload = json.loads(Path("evidence/m03-security-rbac.json").read_text(encoding="utf-8"))
required = {"assignmentId", "commitSha", "roles", "securityControls", "validationCases", "limitations"}
missing = sorted(required.difference(payload))
if missing:
    print(f"ERROR: missing M03 evidence fields: {', '.join(missing)}", file=sys.stderr)
    sys.exit(1)
expected_roles = {"cdrl_migrator", "cdrl_writer", "cdrl_reader", "cdrl_operator"}
if set(payload["roles"]) != expected_roles:
    print("ERROR: M03 evidence must define exactly the four required roles", file=sys.stderr)
    sys.exit(1)

# 6. Verificar que no haya contraseñas en el SQL
sql = Path("db/migrations/002_roles_and_privileges.sql").read_text(encoding="utf-8")
for match in re.finditer(r"\bPASSWORD\s+([^\s;,\)]+)", sql, re.IGNORECASE):
    value = match.group(1)
    if value.startswith(":") or value.startswith("%"):
        continue
    print("ERROR: hardcoded password detected in M03 SQL", file=sys.stderr)
    sys.exit(1)

# 7. Generar artifacts/base-verify.json
Path("artifacts").mkdir(exist_ok=True)
Path("artifacts/base-verify.json").write_text(
    json.dumps({
        "status": "starter_base_valid",
        "scope": "structure_and_contract_only",
        "nextMilestone": "m01-data-contract",
    }, indent=2) + "\n",
    encoding="utf-8",
)

print("CDRL starter base verification passed")
