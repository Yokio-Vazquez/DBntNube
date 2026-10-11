# CDRL — Cloud Data Reliability Lab

Repositorio del equipo para el proyecto **Cloud Data Reliability Lab (CDRL)** de la asignatura **Bases de datos en la nube**. Incluye una API, persistencia relacional y documental, migraciones y pruebas automatizadas.

## Flujo de trabajo

1. Configura `.env` a partir de `.env.example` cuando necesites personalizar el entorno local.
2. Ejecuta `make setup` para iniciar PostgreSQL y DynamoDB Local, aplicar migraciones, cargar datos de prueba y configurar roles.
3. Ejecuta `make verify` para comprobar el contrato del repositorio y correr los tests; el reporte JUnit se genera en `artifacts/test_report.xml`.
4. Inicia la API con `uvicorn src.main:app --reload`.
5. Conserva la evidencia técnica de cada hito y la contribución de cada integrante.

`make setup` prepara PostgreSQL y DynamoDB Local. La tabla `cdrl_events` y sus eventos sintéticos se crean idempotentemente. Para DynamoDB Local las credenciales de ejemplo son valores ficticios. La API consulta eventos con `GET /events?game_id=1`.

El lenguaje de la aplicación lo selecciona el equipo y debe documentarse en un ADR. La interfaz mínima común del repositorio es:

```text
make setup
make verify
make run
```

## Entornos

- AWS Academy Learner Lab es el entorno cloud oficial cuando el servicio esté habilitado.
- Docker Compose/PostgreSQL y el emulador local declarado por el equipo son el respaldo reproducible.
- No uses cuentas personales con facturación, ni subas credenciales, tokens o datos sensibles.

## Entrega de cada hito

En Classroom entrega el repositorio propio del equipo, el tag semanal solicitado, el SHA exacto y el reporte de `make verify`. El repositorio debe conservar el historial y la evidencia de participación técnica de cada integrante.
