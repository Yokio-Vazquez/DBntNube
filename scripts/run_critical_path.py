#!/usr/bin/env python
"""Ruta crítica del sistema CDRL (make run).

Ejecuta de forma no interactiva:
1. Conexión a PostgreSQL con el rol lector y conteo de datos semilla.
2. Conexión a DynamoDB Local y conteo de eventos.
3. Arranque de la API (uvicorn) en un subproceso, prueba de endpoints y apagado.
4. Ciclo de evolución documental M07 (migrate -> migrate idempotente -> rollback)
   sobre la tabla real, dejándola en su estado original.
5. Registro de evidencia en artifacts/run-evidence.json.

Devuelve 0 solo si todos los pasos pasan.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

API_HOST = "127.0.0.1"
API_PORT = int(os.getenv("API_PORT", "8080"))
API_URL = f"http://{API_HOST}:{API_PORT}"
EVIDENCE_PATH = ROOT / "artifacts" / "run-evidence.json"
RUN_MIGRATION_REPORT = ROOT / "artifacts" / "run-m07-cycle.json"
LINE = "=" * 60

evidence: dict = {
    "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "apiUrl": API_URL,
    "steps": [],
}


def record(name: str, ok: bool, **details) -> bool:
    evidence["steps"].append({"step": name, "ok": ok, **details})
    return ok


def check_postgres() -> bool:
    from sqlalchemy import text

    from src.database import reader_engine

    try:
        with reader_engine.connect() as conn:
            games = conn.execute(text("SELECT count(*) FROM games")).scalar_one()
            metrics = conn.execute(
                text("SELECT count(*) FROM game_metrics WHERE deleted_at IS NULL")
            ).scalar_one()
    except Exception as error:  # noqa: BLE001
        print(f"[PostgreSQL] ERROR: {error}")
        return record("postgres", False, error=str(error))

    print(f"[PostgreSQL] OK: conectado a '{os.getenv('DB_NAME', 'cdrl')}' con rol lector.")
    print(f"             - Videojuegos registrados: {games}")
    print(f"             - Métricas activas: {metrics}")
    return record("postgres", games > 0, games=games, activeMetrics=metrics)


def check_dynamodb() -> bool:
    from src.nosql import TABLE_NAME, dynamodb_resource

    try:
        table = dynamodb_resource().Table(TABLE_NAME)
        count = table.scan(Select="COUNT")["Count"]
    except Exception as error:  # noqa: BLE001
        print(f"[DynamoDB]   ERROR: {error}")
        return record("dynamodb", False, error=str(error))

    print(f"[DynamoDB]   OK: tabla '{TABLE_NAME}' disponible.")
    print(f"             - Eventos almacenados: {count}")
    return record("dynamodb", count > 0, table=TABLE_NAME, events=count)


def _get(path: str) -> tuple[int, object]:
    try:
        with urllib.request.urlopen(f"{API_URL}{path}", timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def check_api() -> bool:
    print(f"\n=> Iniciando API en {API_URL} (subproceso uvicorn)...")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app",
         "--host", API_HOST, "--port", str(API_PORT), "--log-level", "warning"],
        cwd=ROOT,
    )
    results = []
    try:
        for _ in range(40):
            if process.poll() is not None:
                print("[API]        ERROR: uvicorn terminó antes de responder.")
                return record("api", False, error="uvicorn exited early")
            try:
                if _get("/health")[0] == 200:
                    break
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(0.5)
        else:
            print("[API]        ERROR: /health no respondió a tiempo.")
            return record("api", False, error="health timeout")

        for path in (
            "/health",
            "/metrics/summary",
            "/events?game_id=1",
            "/events?game_id=1&version=2",
        ):
            status, body = _get(path)
            size = len(body) if isinstance(body, list) else None
            ok = status == 200
            results.append({"path": path, "status": status, "items": size})
            mark = "OK " if ok else "ERR"
            extra = f" ({size} elementos)" if size is not None else ""
            print(f"[API]        {mark} GET {path} -> {status}{extra}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        print("=> API detenida.")

    return record("api", all(r["status"] == 200 for r in results), requests=results)


def _migrate(*extra: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "scripts/migrate_events.py",
         "--report", str(RUN_MIGRATION_REPORT), *extra],
        cwd=ROOT, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return json.loads(completed.stdout)


def check_m07_cycle() -> bool:
    print("\n=> Ciclo de evolución documental M07 sobre la tabla real...")
    RUN_MIGRATION_REPORT.unlink(missing_ok=True)
    try:
        first = _migrate()
        print(f"[M07]        migrate   -> migrados: {first['migrated']}, omitidos: {first['skipped']}")
        second = _migrate()
        print(f"[M07]        migrate   -> migrados: {second['migrated']} (idempotente: {second['idempotent']})")
        back = _migrate("--rollback")
        print(f"[M07]        rollback  -> revertidos: {back['rolledBack']} (estado original: {back['rollbackVerified']})")
    except (RuntimeError, json.JSONDecodeError, KeyError) as error:
        print(f"[M07]        ERROR: {error}")
        return record("m07_cycle", False, error=str(error))

    ok = second["idempotent"] and back["rollbackVerified"]
    return record(
        "m07_cycle", ok,
        migrated=first["migrated"],
        idempotent=second["idempotent"],
        rolledBack=back["rolledBack"],
        rollbackVerified=back["rollbackVerified"],
        report=str(RUN_MIGRATION_REPORT.relative_to(ROOT)),
    )


def main() -> int:
    print(LINE)
    print("        CDRL - Métricas de Videojuegos (PostgreSQL + DynamoDB)")
    print("                  Ejecución de Ruta Crítica")
    print(LINE)

    checks = [check_postgres(), check_dynamodb(), check_api(), check_m07_cycle()]
    success = all(checks)
    evidence["success"] = success

    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(LINE)
    if success:
        print("=> Sistema CDRL operando correctamente.")
    else:
        print("=> FALLO: revisa los pasos marcados con ERROR.")
    print(f"=> Evidencia guardada en {EVIDENCE_PATH.relative_to(ROOT).as_posix()}")
    print("=> Para dejar la API escuchando de forma interactiva: make serve")
    print(LINE)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
