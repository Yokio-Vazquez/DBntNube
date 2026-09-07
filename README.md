# CDRL API - Metricas de videojuegos

API base del proyecto **Cloud Data Reliability Lab (CDRL)** para la asignatura
**Bases de datos en la nube**. La API registra metricas de videojuegos y las
persiste en PostgreSQL mediante el modelo `game_metrics`.

## Que hace la API

- Comprueba que el servicio este disponible mediante `GET /health`.
- Registra una metrica mediante `POST /metrics`.
- Verifica la integridad de los datos y devuelve errores cuando una regla del
	contrato no se cumple.

La API no crea videojuegos. Cada metrica debe referenciar un videojuego que ya
exista en `games`.

## Endpoints

### `GET /health`

Comprueba el estado del servicio y responde `200 OK`:

```json
{
	"status": "ok",
	"message": "API CDRL funcionando correctamente"
}
```

### `POST /metrics`

Registra una metrica de un videojuego. Respuesta exitosa: `201 Created`.

Ejemplo de una calificacion:

```json
{
	"external_id": "metric-001",
	"game_id": 1,
	"metric_name": "rating",
	"metric_value": 4.5,
	"unit": "stars",
	"measured_at": "2026-09-06T20:00:00Z"
}
```

Ejemplo de duracion:

```json
{
	"external_id": "metric-002",
	"game_id": 1,
	"metric_name": "duration",
	"metric_value": 12.5,
	"unit": "hours",
	"measured_at": "2026-09-06T20:00:00Z"
}
```

## Reglas del contrato de datos

| Campo o relacion | Regla |
| --- | --- |
| `games.title` | Es obligatorio y unico. |
| `game_metrics.external_id` | Es obligatorio y unico. |
| `game_metrics.game_id` | Es obligatorio y debe referenciar un registro existente en `games.id`. |
| `rating` | Su valor debe estar entre `0` y `5`, inclusive. |
| `duration` | Su valor debe ser mayor que `0`. |
| `rating` | Solo puede usar la unidad `stars`. |
| `duration` | Solo puede usar la unidad `hours`. |
| `measured_at` | Es obligatorio y debe enviarse en formato ISO 8601. |

Las combinaciones validas son `rating` con `stars` y `duration` con `hours`.
Si se intenta guardar un `game_id` inexistente, la API responde `422`. Un
`external_id` repetido produce `409 Conflict`. Los datos invalidos producen
`422 Unprocessable Entity` y un problema de conexion con PostgreSQL produce
`503 Service Unavailable`.

## Ejecucion local

Requisitos: Docker, Docker Compose, Python y GNU Make.

```text
make setup
make verify
make run
```

`make run` inicia PostgreSQL y DynamoDB Local con Docker Compose. La API usa
PostgreSQL y toma la configuracion de estas variables de entorno:

```text
POSTGRES_USER=cdrl_dev
POSTGRES_PASSWORD=cdrl_dev_only
POSTGRES_DB=cdrl
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

No subas credenciales, tokens ni datos sensibles al repositorio.

## Flujo academico y entregas

1. Crea un repositorio GitHub propio para el equipo; no trabajes sobre el
	repositorio del curso.
2. Agrega unicamente a los integrantes del equipo, con un maximo de tres.
3. Completa cada hito semanal y conserva evidencia tecnica individual.
4. Entrega en Classroom el repositorio, el tag semanal solicitado, el SHA exacto
	y el reporte de `make verify`.

El repositorio debe conservar el historial, las migraciones, los seeds, las
pruebas, los reportes y el ADR correspondiente.
