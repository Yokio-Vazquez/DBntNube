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
2. `make verify` corre el disaster recovery (M06), la demo de evolución documental (M07) y el contrato del repositorio, y después la suite completa de pytest. El reporte JUnit queda en `artifacts/test_report.xml`.
3. `make run` ejecuta la ruta crítica y **termina solo**: verifica PostgreSQL y DynamoDB, levanta la API en `http://127.0.0.1:8080`, prueba `/health`, `/metrics/summary` y `/events`, la detiene y ejecuta el ciclo `migrate → migrate (idempotente) → rollback` sobre `cdrl_events`, dejando la tabla en su estado original. La evidencia queda en `artifacts/run-evidence.json`.
4. Conserva la evidencia técnica de cada hito y la contribución de cada integrante.

Si quieres explorar la API de forma interactiva, ejecuta `make serve`: deja uvicorn escuchando en `http://127.0.0.1:8080` (documentación en `/docs`) hasta que pulses `Ctrl+C`. Usa el puerto 8080 porque DynamoDB Local ocupa el 8000.

El lenguaje de la aplicación lo selecciona el equipo y debe documentarse en un ADR. La interfaz del repositorio es:

```text
make setup          # .venv + dependencias + Docker + DynamoDB + roles + migraciones
make verify         # Contrato + disaster recovery + demo M07 + suite pytest
make run            # Ruta crítica: BD, API (arranca, se prueba y se detiene), ciclo M07
make serve          # (Opcional) API interactiva en :8080, bloquea la terminal
make migrate        # Migrar documentos v1/v2 a v3 en cdrl_events
make rollback       # Revertir migración a versiones originales
```

## Entornos

- AWS Academy Learner Lab es el entorno cloud oficial cuando el servicio esté habilitado.
- Docker Compose/PostgreSQL y el emulador local declarado por el equipo son el respaldo reproducible.
- No uses cuentas personales con facturación, ni subas credenciales, tokens o datos sensibles.

## Entrega de cada hito

En Classroom entrega el repositorio propio del equipo, el tag semanal solicitado, el SHA exacto y el reporte de `make verify`. El repositorio debe conservar el historial y la evidencia de participación técnica de cada integrante.

## Preparación e implementación M07

La [guía corregida](docs/M07-guia-equipo.md) define el trabajo del equipo. La [implementación de Persona 1](docs/M07-persona1-implementacion.md) documenta el API compatible, la configuración de escritura, las funciones compartidas y la validación realizada. La decisión arquitectónica se documenta en [ADR-007](docs/ADR-007-evolucion-documentos.md).
