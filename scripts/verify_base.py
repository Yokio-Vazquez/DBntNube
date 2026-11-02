#!/usr/bin/env python
"""Verificación portable del contrato CDRL (equivalente a verify_base.sh)."""
import json
import os
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
    "db/migrations/003_enforce_role_privileges.sql",
    "scripts/bootstrap_roles.sh",
    "docs/ADR-003-seguridad-rbac.md",
    "evidence/m03-security-rbac.json",
    "docs/ADR-004-decision-nosql.md",
    "artifacts/m04-nosql-decision-results.json",
    ".github/workflows/cdrl-feedback.yml",
    # M05
    "docs/ADR-005-almacen-documental.md",
    "evidence/m05-document-store.json",
    # M06
    "docs/ADR-006-auditoria-recuperacion.md",
    "tests/fixtures/recovery_fixture.json",
    "scripts/disaster_recovery.py",
    "evidence/m06-evolucion-auditoria.json",
    "artifacts/m06-resultados.json",
    # M07
    "docs/ADR-007-evolucion-documentos.md",
    "evidence/m07-document-evolution.json",
    "artifacts/m07-migration-results.json",
    "scripts/migrate_events.py",
    "scripts/m07_demo.py",
    "tests/fixtures/m07_mixed_versions.json",
    "tests/test_m07_compat_read.py",
    "tests/test_m07_migrate_events.py",
    "tests/test_m07_document_evolution.py",
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

# 6. Validar matriz de decisión NoSQL M04
payload = json.loads(Path("artifacts/m04-nosql-decision-results.json").read_text(encoding="utf-8"))
required = {"assignmentId", "decisionStatus", "criteria", "candidates", "selectedCandidate", "sources"}
missing = sorted(required.difference(payload))
if missing:
    print(f"ERROR: missing M04 artifact fields: {', '.join(missing)}", file=sys.stderr)
    sys.exit(1)
if payload["assignmentId"] != "m04-nosql-decision":
    print("ERROR: unexpected M04 assignmentId", file=sys.stderr)
    sys.exit(1)
criteria = payload["criteria"]
weights = {criterion["id"]: criterion["weight"] for criterion in criteria}
if sum(weights.values()) != 100:
    print("ERROR: M04 criterion weights must sum to 100", file=sys.stderr)
    sys.exit(1)
for candidate in payload["candidates"]:
    if set(candidate["scores"]) != set(weights):
        print(f"ERROR: incomplete M04 scores for {candidate['id']}", file=sys.stderr)
        sys.exit(1)
    total = sum(weights[key] * candidate["scores"][key] for key in weights)
    if total != candidate["weightedTotal"] or total / 5 != candidate["normalizedScore"]:
        print(f"ERROR: inconsistent M04 weighted score for {candidate['id']}", file=sys.stderr)
        sys.exit(1)
selected = next((candidate for candidate in payload["candidates"] if candidate["id"] == payload["selectedCandidate"]), None)
if selected is None or selected["normalizedScore"] != max(candidate["normalizedScore"] for candidate in payload["candidates"]):
    print("ERROR: selected M04 candidate is missing or is not the highest scoring option", file=sys.stderr)
    sys.exit(1)

# 7. Verificar que no haya contraseñas en el SQL
sql = Path("db/migrations/002_roles_and_privileges.sql").read_text(encoding="utf-8")
for match in re.finditer(r"\bPASSWORD\s+([^\s;,\)]+)", sql, re.IGNORECASE):
    value = match.group(1)
    if value.startswith(":") or value.startswith("%"):
        continue
    print("ERROR: hardcoded password detected in M03 SQL", file=sys.stderr)
    sys.exit(1)

# 8. Generar artifacts/base-verify.json
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

# ─────────────────────────────────────────────────────────────────────────────
# 8b. Validar evidencia M05
# ─────────────────────────────────────────────────────────────────────────────
payload = json.loads(Path("evidence/m05-document-store.json").read_text(encoding="utf-8"))
required = {"assignmentId", "commitSha", "commands", "results", "testCases", "assumptions", "limitations"}
missing = sorted(required.difference(payload))
if missing:
    print(f"ERROR: missing M05 evidence fields: {', '.join(missing)}", file=sys.stderr)
    sys.exit(1)
if payload["assignmentId"] != "m05-document-store":
    print("ERROR: unexpected M05 assignmentId", file=sys.stderr)
    sys.exit(1)
if len(payload["testCases"]) < 4:
    print("ERROR: M05 evidence must include at least 4 test cases", file=sys.stderr)
    sys.exit(1)
# Verificar que no haya menciones a 'unavailable' en results (Windows workaround)
for key, val in payload.get("results", {}).items():
    if "unavailable" in str(val).lower() and "make" in str(val).lower():
        print(f"ERROR: M05 results['{key}'] contiene referencias a 'GNU Make unavailable' — actualizar con resultados reales", file=sys.stderr)
        sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# 9. Validar evidencia y artefactos M06
# ─────────────────────────────────────────────────────────────────────────────
payload_m06 = json.loads(Path("evidence/m06-evolucion-auditoria.json").read_text(encoding="utf-8"))
required_m06 = {"assignmentId", "commitSha", "team", "auditTests", "recoveryTests", "versionTests"}
missing_m06 = sorted(required_m06.difference(payload_m06))
if missing_m06:
    print(f"ERROR: missing M06 evidence fields: {', '.join(missing_m06)}", file=sys.stderr)
    sys.exit(1)
if len(payload_m06.get("team", [])) < 3:
    print("ERROR: M06 evidence must document contributions from at least 3 personas", file=sys.stderr)
    sys.exit(1)

# Validar m06-resultados.json
payload_m06_res = json.loads(Path("artifacts/m06-resultados.json").read_text(encoding="utf-8"))
required_m06_res = {"assignmentId", "table", "fixture", "disaster", "recovery", "verification"}
missing_m06_res = sorted(required_m06_res.difference(payload_m06_res))
if missing_m06_res:
    print(f"ERROR: missing m06-resultados.json fields: {', '.join(missing_m06_res)}", file=sys.stderr)
    sys.exit(1)
if payload_m06_res.get("verification", {}).get("status") != "success":
    print("ERROR: m06-resultados.json verification.status debe ser 'success'", file=sys.stderr)
    sys.exit(1)

# Validar fixture de recuperacion
fixture = json.loads(Path("tests/fixtures/recovery_fixture.json").read_text(encoding="utf-8"))
if len(fixture.get("items", [])) < 1:
    print("ERROR: recovery_fixture.json debe tener al menos 1 item", file=sys.stderr)
    sys.exit(1)

print("M05 + M06 validation passed")

# ─────────────────────────────────────────────────────────────────────────────
# 10. Validar evidencia, artifact y fixture M07
#     (make verify ejecuta scripts/m07_demo.py antes para regenerar el artifact)
# ─────────────────────────────────────────────────────────────────────────────
def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

evidence_m07 = json.loads(Path("evidence/m07-document-evolution.json").read_text(encoding="utf-8"))
required_m07 = {
    "assignmentId", "commitSha", "team", "compatibilityTests", "migrationTests",
    "rollbackTests", "failureTests", "commands", "results", "assumptions", "limitations",
}
missing_m07 = sorted(required_m07.difference(evidence_m07))
if missing_m07:
    fail(f"missing M07 evidence fields: {', '.join(missing_m07)}")
if evidence_m07["assignmentId"] != "m07-document-evolution":
    fail("unexpected M07 assignmentId")
if not SHA_RE.match(str(evidence_m07["commitSha"])):
    fail("M07 commitSha must be a full 40-character git SHA")
team = evidence_m07["team"]
if sorted(member.get("persona") for member in team) != [1, 2, 3]:
    fail("M07 evidence must document Personas 1, 2 and 3")
for member in team:
    if not member.get("role") or not member.get("files") or not member.get("commitShas"):
        fail(f"M07 persona {member.get('persona')} needs role, files and commitShas")
    if not all(SHA_RE.match(sha) for sha in member["commitShas"]):
        fail(f"M07 persona {member.get('persona')} has an invalid commit SHA")
for section in ("compatibilityTests", "migrationTests", "rollbackTests", "failureTests"):
    if not evidence_m07[section]:
        fail(f"M07 evidence section {section} is empty")
if not evidence_m07["limitations"]:
    fail("M07 evidence must declare limitations")

artifact_m07 = json.loads(Path("artifacts/m07-migration-results.json").read_text(encoding="utf-8"))
if artifact_m07.get("assignmentId") != "m07-document-evolution":
    fail("unexpected M07 artifact assignmentId")
if artifact_m07.get("table") in {"cdrl_events", os.getenv("DYNAMODB_TABLE", "cdrl_events")}:
    fail("M07 artifact must come from the isolated test table, not cdrl_events")
if artifact_m07.get("idempotent") is not True or artifact_m07.get("rollbackVerified") is not True:
    fail("M07 artifact must report idempotent == true and rollbackVerified == true")
runs = artifact_m07.get("runs", [])
if [run.get("operation") for run in runs] != ["migrate", "migrate", "rollback"] or any(
    run.get("dryRun") is not False for run in runs
):
    fail("M07 artifact must contain exactly migrate, migrate, rollback real runs")
first, second, rollback = runs
if (first.get("migrated"), first.get("skipped"), first.get("failed")) != (4, 1, 1):
    fail("M07 first migration must report migrated=4, skipped=1, failed=1")
if second.get("migrated") != 0 or rollback.get("rolledBack") != 4:
    fail("M07 second migration must migrate 0 and rollback must restore 4")
for run in runs:
    details = run.get("failureDetails", [])
    if [detail.get("event_key") for detail in details] != ["m07-invalid"]:
        fail("M07 runs must report only the expected invalid document")
    if not (HASH_RE.match(str(run.get("snapshotBefore"))) and HASH_RE.match(str(run.get("snapshotAfter")))):
        fail("M07 runs must include SHA-256 snapshots")
initial = artifact_m07.get("initialSnapshot")
if not (
    initial == first["snapshotBefore"] == rollback["snapshotAfter"]
    and first["snapshotAfter"] == second["snapshotBefore"] == second["snapshotAfter"]
):
    fail("M07 artifact snapshots do not prove idempotence and exact rollback")
if artifact_m07.get("expectations") and not all(artifact_m07["expectations"].values()):
    fail("M07 artifact contains failed expectations")

fixture_m07 = json.loads(Path("tests/fixtures/m07_mixed_versions.json").read_text(encoding="utf-8"))
versions = sorted(str(item.get("schemaVersion", "implicit-1")) for item in fixture_m07.get("items", []))
if versions != sorted(["implicit-1", "1", "2", "2", "3", "99"]):
    fail("m07_mixed_versions.json must contain v1 implicit/explicit, two v2, native v3 and one invalid")
if any(item.get("source") != "synthetic-fixture" for item in fixture_m07["items"]):
    fail("m07_mixed_versions.json must only contain synthetic data")

print("M07 validation passed")

# ─────────────────────────────────────────────────────────────────────────────
# 11. Validar archivos, evidencia y artifacts M08
# ─────────────────────────────────────────────────────────────────────────────
REQUIRED_M08 = [
    "docs/ADR-008-paginacion-indices-rendimiento.md",
    "docs/M08-reporte-rendimiento.md",
    "evidence/m08-pagination-performance.json",
    "artifacts/m08-benchmark-results.json",
    "scripts/m08_benchmark.py",
    "src/pagination.py",
    "tests/test_m08_pagination.py",
    "tests/test_m08_pagination_unit.py",
    "tests/test_m08_benchmark_unit.py",
    "docs/M08-persona1-implementacion.md",
    "docs/M08-persona2-correcciones.md",
]
for f in REQUIRED_M08:
    if not Path(f).is_file():
        fail(f"missing M08 required file: {f}")

# --- Evidencia M08 ---
evidence_m08 = json.loads(Path("evidence/m08-pagination-performance.json").read_text(encoding="utf-8"))
required_m08_ev = {
    "assignmentId", "commitSha", "team", "paginationTests", "benchmark",
    "baselineComparison", "tradeOffs", "environment", "commands", "results",
    "assumptions", "limitations",
}
missing_m08_ev = sorted(required_m08_ev.difference(evidence_m08))
if missing_m08_ev:
    fail(f"missing M08 evidence fields: {', '.join(missing_m08_ev)}")
if evidence_m08["assignmentId"] != "m08-pagination-performance":
    fail("unexpected M08 assignmentId")
if not SHA_RE.match(str(evidence_m08["commitSha"])):
    fail("M08 commitSha must be a full 40-character git SHA")
team_m08 = evidence_m08["team"]
if sorted(member.get("persona") for member in team_m08) != [1, 2, 3]:
    fail("M08 evidence must document Personas 1, 2 and 3")
for member in team_m08:
    if not member.get("role") or not member.get("commitShas") or not member.get("files"):
        fail(f"M08 persona {member.get('persona')} needs role, files and commitShas")
    if not all(SHA_RE.match(sha) for sha in member["commitShas"]):
        fail(f"M08 persona {member.get('persona')} has an invalid commit SHA")
if not evidence_m08["limitations"]:
    fail("M08 evidence must declare limitations")

# --- Artifact M08 quick ---
artifact_m08 = json.loads(Path("artifacts/m08-benchmark-results.json").read_text(encoding="utf-8"))
if artifact_m08.get("assignmentId") != "m08-pagination-performance":
    fail("unexpected M08 artifact assignmentId")
if artifact_m08.get("table") in {"cdrl_events", os.getenv("DYNAMODB_TABLE", "cdrl_events")}:
    fail("M08 artifact must come from an isolated table, not cdrl_events")
if not artifact_m08.get("environment"):
    fail("M08 artifact must include environment")
if not artifact_m08.get("dataset", {}).get("seed"):
    fail("M08 artifact must include dataset.seed")

# Validate readComparison: both strategies use the same table.
read_comp = artifact_m08.get("readComparison", {})
if read_comp.get("baselineTable") != read_comp.get("indexedTable") or read_comp.get("samePhysicalTable") is not True:
    fail("M08 readComparison: both strategies must use the same physical table")

# Validate scenarios.
expected_scenarios = {
    f"{strategy}_{kind}"
    for strategy in ("baseline", "indexed")
    for kind in ("page1", "deep", "walk")
}
if set(artifact_m08.get("scenarios", {})) != expected_scenarios:
    fail(f"M08 artifact must contain exactly {expected_scenarios}")
iterations = artifact_m08.get("config", {}).get("iterations")
for name, scenario in artifact_m08.get("scenarios", {}).items():
    if iterations and scenario.get("samples") != iterations:
        fail(f"M08 scenario {name}: samples ({scenario.get('samples')}) != iterations ({iterations})")
    if scenario.get("errors", -1) != 0:
        fail(f"M08 scenario {name}: errors must be 0")
    latency = scenario.get("latencyMs", {})
    if latency.get("p50", 0) > latency.get("p95", -1):
        fail(f"M08 scenario {name}: p50 > p95")

# Validate comparison is not empty.
comparison = artifact_m08.get("comparison", {})
if not comparison:
    fail("M08 artifact comparison must not be empty")

# Validate correctness.
correctness = artifact_m08.get("correctness", {})
if correctness.get("sameResultSet") is not True:
    fail("M08 correctness.sameResultSet must be true")

# Validate gate.
gate = artifact_m08.get("gate", {})
if gate.get("passed") is not True:
    fail("M08 gate must pass")
scenarios = artifact_m08.get("scenarios", {})
if scenarios.get("indexed_deep", {}).get("itemsRead", float("inf")) >= scenarios.get("baseline_deep", {}).get(
    "itemsRead", 0
):
    fail("M08 gate: indexed_deep.itemsRead must be less than baseline_deep.itemsRead")

print("M08 validation passed")
