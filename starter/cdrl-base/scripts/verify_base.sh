#!/usr/bin/env bash
set -euo pipefail

required_files=(
  ".env.example"
  "Makefile"
  "docker-compose.yml"
  "docs/ADR-000-starter-base.md"
  "evidence/m01-data-contract.json"
  "alembic/versions/b7c2d9e4f1a0_m02_relational_model.py"
  "db/migrations/002_create_relational_model.sql"
  "db/seed/002_seed_relational_model.sql"
  "db/queries/002_parametrized_relational_queries.sql"
  "docs/ADR-002-modelo-relacional.md"
  "evidence/m02-relational-model.json"
  "artifacts/m02-relational-model-results.json"
  ".github/workflows/cdrl-feedback.yml"
)

for required in "${required_files[@]}"; do
  test -f "$required" || { echo "missing required file: $required" >&2; exit 1; }
done

if command -v docker >/dev/null 2>&1; then
  docker compose config --quiet
fi

python3 - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("evidence/m01-data-contract.json").read_text())
required = {"assignmentId", "commitSha", "commands", "results", "assumptions", "limitations"}
missing = sorted(required.difference(payload))
if missing:
    raise SystemExit(f"missing evidence fields: {', '.join(missing)}")
PY

python3 - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("evidence/m02-relational-model.json").read_text())
required = {
    "assignmentId", "commitSha", "commands", "results", "schema",
    "invariants", "testCases", "assumptions", "limitations"
}
missing = sorted(required.difference(payload))
if missing:
    raise SystemExit(f"missing M02 evidence fields: {', '.join(missing)}")
if payload["assignmentId"] != "m02-relational-model":
    raise SystemExit("unexpected M02 assignmentId")
if len(payload["testCases"]) < 4:
    raise SystemExit("M02 evidence must include normal, empty, boundary and failure cases")
PY

mkdir -p artifacts
python3 - <<'PY'
import json
from pathlib import Path

Path("artifacts/base-verify.json").write_text(json.dumps({
    "status": "starter_base_valid",
    "scope": "structure_and_contract_only",
    "nextMilestone": "m01-data-contract"
}, indent=2) + "\n")
PY

echo "CDRL starter base verification passed"
