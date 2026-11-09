# CDRL — Cloud Data Reliability Lab

Repositorio del equipo para el proyecto **Cloud Data Reliability Lab (CDRL)** de la asignatura **Bases de datos en la nube**. Incluye una API, persistencia relacional y documental, migraciones y pruebas automatizadas.

## Flujo de trabajo (automático, en este orden)

```bash
make setup    # 1. Entorno
make verify   # 2. Verificación
make run      # 3. Ruta crítica
```

Requisitos: Docker (con `docker compose`), Python 3.11+ y GNU Make. No hace falta ningún paso manual: no tienes que crear `.env`, instalar dependencias ni arrancar la API a mano.

1. `make setup` copia `.env.example` a `.env` si no existe, crea el entorno virtual `.venv`, instala `requirements.txt`, levanta PostgreSQL y DynamoDB Local (`docker compose up -d --wait`), crea la tabla `cdrl_events` con eventos sintéticos, aplica roles y ejecuta las migraciones de Alembic.
2. `make verify` corre el disaster recovery (M06), la demo de evolución documental (M07), el benchmark de paginación M08 (modo quick), el contrato del repositorio y la suite completa de pytest. El reporte JUnit queda en `artifacts/test_report.xml`.
3. `make run` ejecuta la ruta crítica y **termina solo**: verifica PostgreSQL y DynamoDB, levanta la API en `http://127.0.0.1:8080`, prueba `/health`, `/metrics/summary`, `/events` y `/events/page`, la detiene y ejecuta el ciclo `migrate → migrate (idempotente) → rollback` sobre `cdrl_events`, dejando la tabla en su estado original. La evidencia queda en `artifacts/run-evidence.json`.
4. Conserva la evidencia técnica de cada hito y la contribución de cada integrante.

Si quieres explorar la API de forma interactiva, ejecuta `make serve`: deja uvicorn escuchando en `http://127.0.0.1:8080` (documentación en `/docs`) hasta que pulses `Ctrl+C`. Usa el puerto 8080 porque DynamoDB Local ocupa el 8000.

El lenguaje de la aplicación lo selecciona el equipo y debe documentarse en un ADR. La interfaz del repositorio es:

```text
make setup          # .venv + dependencias + Docker + DynamoDB + roles + migraciones
make verify         # Contrato + disaster recovery + demo M07 + benchmark M08 + suite pytest
make run            # Ruta crítica: BD, API (arranca, se prueba y se detiene), ciclo M07
make serve          # (Opcional) API interactiva en :8080, bloquea la terminal
make migrate        # Migrar documentos v1/v2 a v3 en cdrl_events
make rollback       # Revertir migración a versiones originales
make bench          # Benchmark completo M08 (modo full) → artifacts/m08-benchmark-full.json
```

## Entornos

- AWS Academy Learner Lab es el entorno cloud oficial cuando el servicio esté habilitado.
- Docker Compose/PostgreSQL y el emulador local declarado por el equipo son el respaldo reproducible.
- No uses cuentas personales con facturación, ni subas credenciales, tokens o datos sensibles.

## Entrega de cada hito

En Classroom entrega el repositorio propio del equipo, el tag semanal solicitado, el SHA exacto y el reporte de `make verify`. El repositorio debe conservar el historial y la evidencia de participación técnica de cada integrante.

## Preparación e implementación M07

La [guía corregida](docs/M07-guia-equipo.md) define el trabajo del equipo. La [implementación de Persona 1](docs/M07-persona1-implementacion.md) documenta el API compatible, la configuración de escritura, las funciones compartidas y la validación realizada. La decisión arquitectónica se documenta en [ADR-007](docs/ADR-007-evolucion-documentos.md).

## M08 — Paginación, índices y rendimiento

### Endpoint nuevo: `GET /events/page`

```text
GET /events/page?game_id=1&limit=25&cursor=<opaco>&version=3
→ 200 { "items": [...], "nextCursor": "..." | null, "limit": 25, "order": "occurred_at_desc" }
→ 400 cursor inválido o de otro game_id
→ 422 limit fuera de rango, game_id <= 0 o version fuera de 1..3
→ 503 DynamoDB no disponible
```

El cursor es opaco (base64url de un JSON versionado). Para recorrer todas las páginas, usar el `nextCursor` de cada respuesta hasta obtener `null`. El endpoint `GET /events` sigue funcionando sin cambios para compatibilidad con M04–M07.

### Variables de configuración

| Variable | Default | Descripción |
|---|---|---|
| `EVENTS_PAGE_DEFAULT_LIMIT` | 25 | Tamaño de página por defecto |
| `EVENTS_PAGE_MAX_LIMIT` | 100 | Tamaño máximo permitido |
| `DYNAMODB_TABLE_M08_TEST` | cdrl_events_m08_test | Tabla aislada para benchmark |
| `M08_BENCH_SEED` | 20261031 | Semilla del generador |

### Benchmark

```bash
python scripts/m08_benchmark.py --quick   # Corrida rápida (~2 min)
make bench                                 # Corrida completa (×5)
```

Los artifacts se guardan en `artifacts/m08-benchmark-results.json` (quick, regenerado por `make verify`) y `artifacts/m08-benchmark-full.json` (full, manual).

### Documentación

- [ADR-008 — Índice cronológico, paginación y rendimiento](docs/ADR-008-paginacion-indices-rendimiento.md)
- [Reporte de rendimiento](docs/M08-reporte-rendimiento.md)
- [Implementación Persona 1](docs/M08-persona1-implementacion.md)
- [Correcciones Persona 2](docs/M08-persona2-correcciones.md)

## M09 — Controles por colección y auditoría

### Matriz de autorización (ADR-009)

| Identidad de servicio | Consultar y paginar (`GET /events`, `GET /events/page`) | Crear (`POST /events`) | Actualizar o borrar por HTTP |
|---|---|---|---|
| Lector (`reader`) | Permitido (200) | 403 (Denegado) | Sin ruta |
| Escritor (`writer`) | Permitido (200) | Permitido (201) | Sin ruta |
| Sin credencial válida / Colisión | 401 (Denegado) | 401 (Denegado) | Sin ruta |

### Variables de configuración

| Variable | Descripción |
|---|---|
| `EVENTS_READER_TOKEN` | Token Bearer para identidad de servicio `reader` |
| `EVENTS_WRITER_TOKEN` | Token Bearer para identidad de servicio `writer` |

### Casos demostrados y verificación

```bash
python scripts/verify_m09_controls.py
python -m pytest tests/test_event_access.py tests/test_m09_event_audit.py -v
```

El script genera `artifacts/m09-collection-controls-results.json` y `artifacts/m09-controles-coleccion-results.json`, verificando los 4 casos (Normal, Límite lectura, Límite escritura, Fallo declarado), la persistencia en `audit_logs` con los cuatro campos obligatorios y la exclusión estricta de marcadores y secretos.

### Documentación M09

- [ADR-009 — Controles de eventos](docs/ADR-009-controles-eventos.md)
- [Plan de trabajo del equipo](docs/plan-equipo-controles-por-coleccion.md)
- [Auditoría y remediación Persona 2](docs/M09-persona2-auditoria.md)
- [Reporte de entrega Persona 2](docs/M09-persona2-entrega.md)
- [Guía de entrega Persona 3](docs/M09-persona3-pruebas-entrega.md)
- [Reporte de entrega Persona 3](docs/M09-persona3-entrega.md)
