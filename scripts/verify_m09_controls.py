#!/usr/bin/env python
"""
scripts/verify_m09_controls.py — Verificación y reporte del hito M09 (Persona 3).

Automatiza la demostración de los 4 casos exigidos por el plan de equipo:
1. Normal: creación autorizada (escritor) y consulta autorizada (lector).
2. Límite 1 (Lectura): consulta sin credencial se deniega con 401 y omite contenido.
3. Límite 2 (Escritura): creación con credencial de lector se deniega con 403.
4. Fallo Declarado: colisión de credenciales lector/escritor falla cerrado con 401.

Comprueba los 4 campos obligatorios de cada evento de auditoría:
  - actor_id
  - action
  - resource_type
  - outcome

Verifica la exclusión total de marcadores sintéticos sensibles en auditoría y artifacts.
Genera artifacts/m09-collection-controls-results.json (y m09-controles-coleccion-results.json).
Devuelve código de salida 0 solo si todos los casos pasan.
"""
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# Asegurar path raíz
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from src import main
from src.database import get_db_writer


class CaptureAuditSession:
    """Sesión de auditoría en memoria para aislar la corrida y capturar registros."""

    def __init__(self):
        self.pending = []
        self.persisted = []

    def execute(self, statement):
        table_name = getattr(getattr(statement, "table", None), "name", "unknown")
        params = statement.compile().params
        self.pending.append({"_table": table_name, **params})
        return SimpleNamespace(rowcount=1)

    def commit(self):
        self.persisted.extend(self.pending)
        self.pending.clear()

    def rollback(self):
        self.pending.clear()


class MemoryStorage:
    """Almacén documental aislado para no alterar DynamoDB compartido."""

    def __init__(self):
        self.events = {}

    def query_events(self, game_id: int):
        return [doc for doc in self.events.values() if doc.get("game_id") == game_id]

    def query_events_page(self, game_id: int, limit: int = 25, cursor: str | None = None):
        items = self.query_events(game_id)
        return {
            "items": items[:limit],
            "nextCursor": None,
            "limit": limit,
            "order": "occurred_at_desc",
        }

    def create_event(self, event, audit_operation_id: str | None = None):
        key = (event.game_id, event.event_key)
        if key in self.events:
            return False
        doc = event.model_dump() if hasattr(event, "model_dump") else dict(event)
        if audit_operation_id:
            doc["_audit_operation_id"] = audit_operation_id
        self.events[key] = doc
        return True


def run_verification() -> tuple[dict, bool]:
    reader_token = f"reader-token-{secrets.token_urlsafe(16)}"
    writer_token = f"writer-token-{secrets.token_urlsafe(16)}"
    os.environ["EVENTS_READER_TOKEN"] = reader_token
    os.environ["EVENTS_WRITER_TOKEN"] = writer_token

    storage = MemoryStorage()
    session = CaptureAuditSession()

    original_query = main.query_events
    original_page = main.query_events_page
    original_create = main.create_event

    main.query_events = storage.query_events
    main.query_events_page = storage.query_events_page
    main.create_event = storage.create_event

    def override_session():
        yield session

    previous_override = main.app.dependency_overrides.get(get_db_writer)
    main.app.dependency_overrides[get_db_writer] = override_session

    client = TestClient(main.app)

    # Marcador sintético que debe excluirse de logs y evidencia
    marker_secret = f"SENSITIVE_SECRET_MARKER_{secrets.token_hex(8)}"

    cases_results = []
    all_passed = True

    try:
        # ─────────────────────────────────────────────────────────────────────
        # Caso 1: Normal
        # ─────────────────────────────────────────────────────────────────────
        game_id_1 = 921
        event_key_1 = f"m09-normal-{secrets.token_hex(4)}"
        event_1 = {
            "game_id": game_id_1,
            "event_key": event_key_1,
            "event_type": "m09_normal_event",
            "occurred_at": "2026-11-08T19:00:00Z",
            "source": "m09-verify",
        }
        if main.EventDocument.model_fields.get("schema_version") and main.EventDocument.model_fields["schema_version"].default == 3:
            event_1["platform"] = "pc"

        session_start_idx = len(session.persisted)

        # POST por escritor con marcador sensible en header
        post_res = client.post(
            "/events",
            json=event_1,
            headers={
                "Authorization": f"Bearer {writer_token}",
                "X-Synthetic-Header-Secret": marker_secret,
            },
        )
        # GET /events por lector
        get_res = client.get(
            f"/events?game_id={game_id_1}",
            headers={"Authorization": f"Bearer {reader_token}"},
        )
        # GET /events/page por lector
        page_res = client.get(
            f"/events/page?game_id={game_id_1}&limit=10",
            headers={"Authorization": f"Bearer {reader_token}"},
        )

        normal_audits = [
            r for r in session.persisted[session_start_idx:]
            if r.get("resource_type") == "events"
        ]

        key_in_get = any(it.get("event_key") == event_key_1 for it in (get_res.json() if get_res.status_code == 200 else []))
        key_in_page = any(it.get("event_key") == event_key_1 for it in (page_res.json().get("items", []) if page_res.status_code == 200 else []))

        normal_ok = (
            post_res.status_code == 201
            and get_res.status_code == 200
            and page_res.status_code == 200
            and key_in_get
            and key_in_page
            and len(normal_audits) == 3
            and normal_audits[0]["outcome"] == "success" and normal_audits[0]["actor_id"] == "writer"
            and normal_audits[1]["outcome"] == "success" and normal_audits[1]["actor_id"] == "reader"
            and normal_audits[2]["outcome"] == "success" and normal_audits[2]["actor_id"] == "reader"
        )
        if not normal_ok:
            all_passed = False

        cases_results.append({
            "id": "normal",
            "name": "Normal: creación autorizada y consulta autorizada",
            "expected": {
                "postStatus": 201,
                "getEventsStatus": 200,
                "getPageStatus": 200,
                "keyRecoveredInBothQueries": True,
                "auditOutcomes": ["success", "success", "success"],
                "auditActors": ["writer", "reader", "reader"],
            },
            "observed": {
                "postStatus": post_res.status_code,
                "getEventsStatus": get_res.status_code,
                "getPageStatus": page_res.status_code,
                "keyRecoveredInBothQueries": key_in_get and key_in_page,
                "auditOutcomes": [r["outcome"] for r in normal_audits],
                "auditActors": [r["actor_id"] for r in normal_audits],
            },
            "status": "passed" if normal_ok else "failed",
        })

        # ─────────────────────────────────────────────────────────────────────
        # Caso 2: Límite 1 · Lectura
        # ─────────────────────────────────────────────────────────────────────
        game_id_2 = 922
        event_key_2 = f"m09-boundary-read-{secrets.token_hex(4)}"
        event_2 = {
            "game_id": game_id_2,
            "event_key": event_key_2,
            "event_type": "m09_secret_read_doc",
            "occurred_at": "2026-11-08T19:05:00Z",
            "source": "m09-verify",
        }
        storage.events[(game_id_2, event_key_2)] = event_2

        session_start_idx = len(session.persisted)

        # GET /events sin credencial
        unauth_get = client.get(f"/events?game_id={game_id_2}")
        # GET /events/page sin credencial
        unauth_page = client.get(f"/events/page?game_id={game_id_2}")

        bound_read_audits = [
            r for r in session.persisted[session_start_idx:]
            if r.get("resource_type") == "events"
        ]

        body_omits_content = (
            event_key_2 not in unauth_get.text
            and "m09_secret_read_doc" not in unauth_get.text
            and event_key_2 not in unauth_page.text
        )

        bound_read_ok = (
            unauth_get.status_code == 401
            and unauth_page.status_code == 401
            and body_omits_content
            and len(bound_read_audits) == 2
            and all(r["outcome"] == "denied" and r["actor_id"] == "anonymous" for r in bound_read_audits)
        )
        if not bound_read_ok:
            all_passed = False

        cases_results.append({
            "id": "boundary_read",
            "name": "Límite 1 (Lectura): consulta no autenticada rechazada sin revelar datos",
            "expected": {
                "getEventsStatus": 401,
                "getPageStatus": 401,
                "bodyOmitsDocument": True,
                "auditOutcomes": ["denied", "denied"],
                "auditActors": ["anonymous", "anonymous"],
            },
            "observed": {
                "getEventsStatus": unauth_get.status_code,
                "getPageStatus": unauth_page.status_code,
                "bodyOmitsDocument": body_omits_content,
                "auditOutcomes": [r["outcome"] for r in bound_read_audits],
                "auditActors": [r["actor_id"] for r in bound_read_audits],
            },
            "status": "passed" if bound_read_ok else "failed",
        })

        # ─────────────────────────────────────────────────────────────────────
        # Caso 3: Límite 2 · Escritura
        # ─────────────────────────────────────────────────────────────────────
        game_id_3 = 923
        event_key_3 = f"m09-boundary-write-{secrets.token_hex(4)}"
        event_3 = {
            "game_id": game_id_3,
            "event_key": event_key_3,
            "event_type": "m09_reader_write_attempt",
            "occurred_at": "2026-11-08T19:10:00Z",
            "source": "m09-verify",
        }

        session_start_idx = len(session.persisted)

        # Lector intenta POST /events
        reader_post = client.post(
            "/events",
            json=event_3,
            headers={
                "Authorization": f"Bearer {reader_token}",
                "X-Synthetic-Header-Secret": marker_secret,
            },
        )
        key_absent_in_storage = (game_id_3, event_key_3) not in storage.events

        # Consulta posterior con lector confirma que la clave sigue ausente
        reader_check_get = client.get(
            f"/events?game_id={game_id_3}",
            headers={"Authorization": f"Bearer {reader_token}"},
        )
        key_absent_in_api = not any(it.get("event_key") == event_key_3 for it in (reader_check_get.json() if reader_check_get.status_code == 200 else []))

        bound_write_audits = [
            r for r in session.persisted[session_start_idx:]
            if r.get("resource_type") == "events"
        ]

        bound_write_ok = (
            reader_post.status_code == 403
            and key_absent_in_storage
            and key_absent_in_api
            and len(bound_write_audits) >= 1
            and bound_write_audits[0]["outcome"] == "denied"
            and bound_write_audits[0]["actor_id"] == "reader"
            and bound_write_audits[0]["action"] == "create"
        )
        if not bound_write_ok:
            all_passed = False

        cases_results.append({
            "id": "boundary_write",
            "name": "Límite 2 (Escritura): creación rechazada con credencial de lector",
            "expected": {
                "postStatus": 403,
                "documentRemainsAbsent": True,
                "auditOutcome": "denied",
                "auditActor": "reader",
                "auditAction": "create",
            },
            "observed": {
                "postStatus": reader_post.status_code,
                "documentRemainsAbsent": key_absent_in_storage and key_absent_in_api,
                "auditOutcome": bound_write_audits[0]["outcome"] if bound_write_audits else None,
                "auditActor": bound_write_audits[0]["actor_id"] if bound_write_audits else None,
                "auditAction": bound_write_audits[0]["action"] if bound_write_audits else None,
            },
            "status": "passed" if bound_write_ok else "failed",
        })

        # ─────────────────────────────────────────────────────────────────────
        # Caso 4: Fallo Declarado
        # ─────────────────────────────────────────────────────────────────────
        shared_colliding_token = "identical-shared-secret-collision"
        os.environ["EVENTS_READER_TOKEN"] = shared_colliding_token
        os.environ["EVENTS_WRITER_TOKEN"] = shared_colliding_token

        game_id_4 = 924
        event_key_4 = f"m09-collision-{secrets.token_hex(4)}"
        event_4 = {
            "game_id": game_id_4,
            "event_key": event_key_4,
            "event_type": "m09_collision_event",
            "occurred_at": "2026-11-08T19:15:00Z",
            "source": "m09-verify",
        }

        session_start_idx = len(session.persisted)

        collision_post = client.post(
            "/events",
            json=event_4,
            headers={"Authorization": f"Bearer {shared_colliding_token}"},
        )
        collision_absent = (game_id_4, event_key_4) not in storage.events

        # Restablecer entorno
        os.environ["EVENTS_READER_TOKEN"] = reader_token
        os.environ["EVENTS_WRITER_TOKEN"] = writer_token

        collision_audits = [
            r for r in session.persisted[session_start_idx:]
            if r.get("resource_type") == "events"
        ]

        declared_failure_ok = (
            collision_post.status_code == 401
            and collision_absent
            and len(collision_audits) == 1
            and collision_audits[0]["outcome"] == "denied"
            and collision_audits[0]["actor_id"] == "anonymous"
            and collision_audits[0]["action"] == "create"
        )
        if not declared_failure_ok:
            all_passed = False

        cases_results.append({
            "id": "declared_failure",
            "name": "Fallo Declarado: colisión de credenciales lector/escritor falla de forma cerrada",
            "expected": {
                "postStatus": 401,
                "documentNotCreated": True,
                "auditOutcome": "denied",
                "auditActor": "anonymous",
                "auditAction": "create",
            },
            "observed": {
                "postStatus": collision_post.status_code,
                "documentNotCreated": collision_absent,
                "auditOutcome": collision_audits[0]["outcome"] if collision_audits else None,
                "auditActor": collision_audits[0]["actor_id"] if collision_audits else None,
                "auditAction": collision_audits[0]["action"] if collision_audits else None,
            },
            "status": "passed" if declared_failure_ok else "failed",
        })

        # ─────────────────────────────────────────────────────────────────────
        # Comprobación de los 4 campos obligatorios y marcador sensible
        # ─────────────────────────────────────────────────────────────────────
        all_audits = [
            r for r in session.persisted
            if r.get("resource_type") == "events"
        ]

        mandatory_fields_valid = True
        for row in all_audits:
            for field in ("actor_id", "action", "resource_type", "outcome"):
                if field not in row or not row[field]:
                    mandatory_fields_valid = False

        marker_found_in_logs = marker_secret in str(session.persisted)
        if marker_found_in_logs or not mandatory_fields_valid:
            all_passed = False

        marker_check = {
            "mandatoryFieldsPresent": mandatory_fields_valid,
            "mandatoryFields": ["actor_id", "action", "resource_type", "outcome"],
            "markerFoundInAuditLogs": marker_found_in_logs,
            "passed": mandatory_fields_valid and not marker_found_in_logs,
        }

        # ─────────────────────────────────────────────────────────────────────
        # Vinculación con Remediación de Persona 2
        # ─────────────────────────────────────────────────────────────────────
        remediation_check = {
            "remediationDefect": "Ausencia de registro de auditoría al denegar creación a rol reader",
            "persona2Commit": "f0b0385a68f2e74b336933a114567a67536172de",
            "regressionTest": "test_reader_create_denial_is_audited_without_request_marker",
            "verified": bound_write_ok,
        }

    finally:
        # Restaurar estado original
        main.query_events = original_query
        main.query_events_page = original_page
        main.create_event = original_create
        if previous_override is None:
            main.app.dependency_overrides.pop(get_db_writer, None)
        else:
            main.app.dependency_overrides[get_db_writer] = previous_override

    artifact = {
        "assignmentId": "m09-collection-controls",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "cases": cases_results,
        "markerExclusionCheck": marker_check,
        "remediation": remediation_check,
        "summary": {
            "totalCases": len(cases_results),
            "passed": sum(1 for c in cases_results if c["status"] == "passed"),
            "failed": sum(1 for c in cases_results if c["status"] == "failed"),
            "allPassed": all_passed,
        },
    }

    return artifact, all_passed


def main_cli() -> int:
    print("=" * 70)
    print("  CDRL M09 — Verificación de Controles por Colección y Auditoría")
    print("=" * 70)

    artifact, ok = run_verification()

    for c in artifact["cases"]:
        status_symbol = "[OK]" if c["status"] == "passed" else "[FAIL]"
        print(f" {status_symbol} {c['name']}")
        print(f"      Esperado: {json.dumps(c['expected'])}")
        print(f"      Observado: {json.dumps(c['observed'])}")

    marker_sym = "[OK]" if artifact["markerExclusionCheck"]["passed"] else "[FAIL]"
    print(f" {marker_sym} Verificación de 4 campos obligatorios y exclusión de secretos")

    rem_sym = "[OK]" if artifact["remediation"]["verified"] else "[FAIL]"
    print(f" {rem_sym} Regresión de remediación de Persona 2")

    print("-" * 70)
    print(f" Resumen: {artifact['summary']['passed']}/{artifact['summary']['totalCases']} casos pasaron.")

    # Guardar artefactos
    artifacts_dir = ROOT / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)

    out_file_en = artifacts_dir / "m09-collection-controls-results.json"
    out_file_es = artifacts_dir / "m09-controles-coleccion-results.json"

    content = json.dumps(artifact, indent=2, ensure_ascii=False) + "\n"
    out_file_en.write_text(content, encoding="utf-8")
    out_file_es.write_text(content, encoding="utf-8")
    print(f" Artefactos generados en:")
    print(f"   - {out_file_en.relative_to(ROOT)}")
    print(f"   - {out_file_es.relative_to(ROOT)}")

    if not ok:
        print("ERROR: La verificación del hito M09 falló.", file=sys.stderr)
        return 1

    print("Verificación de controles M09 completada con éxito.")
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())

