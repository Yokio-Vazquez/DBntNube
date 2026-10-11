# ADR-005 - Almacen documental de eventos

## Estado

Aceptada para el alcance funcional de M05. DynamoDB Local es el entorno reproducible por defecto; la validacion de rendimiento y disponibilidad en AWS queda pendiente.

## Contexto

PostgreSQL conserva el catalogo relacional y sus restricciones. DynamoDB almacena eventos complementarios, sinteticos durante desarrollo y pruebas. La tabla existente `cdrl_events` usa `game_id` como clave de particion y `event_key` como clave de ordenamiento, lo que permite recuperar eventos de un juego con `Query`.

M05 agrega consultas por tipo de evento y una ventana temporal. Un `Scan` no escala como patron de consulta y no debe usarse para este acceso.

## Patrones de acceso

1. Recuperar los eventos de un juego mediante la clave primaria: `game_id = :game_id`.
2. Recuperar los eventos de un tipo dentro de un intervalo: `event_type = :event_type` y `occurred_at BETWEEN :from AND :to`.

Los valores de `occurred_at` deben escribirse en formato UTC ISO 8601 canonico, por ejemplo `2026-10-04T12:30:00Z`. Este formato conserva el orden cronologico al comparar las claves de cadena.

## Decision

Se conserva la clave primaria de la tabla y se declara el siguiente indice secundario global:

| Indice | Partition key | Sort key | Proyeccion | Uso |
| --- | --- | --- | --- | --- |
| `event-type-occurred-at-index` | `event_type` (S) | `occurred_at` (S) | `ALL` | Consultar eventos de un tipo en un intervalo temporal y devolver el documento completo. |

La proyeccion `ALL` permite devolver los atributos del evento desde la consulta al GSI, sin una lectura adicional de la tabla. Esto aumenta el almacenamiento y el costo de escritura del indice; se acepta para el alcance actual y debe revisarse si crece el volumen o el tamano de los documentos.

`scripts/init_dynamodb.py` llama a `ensure_events_table` en `src/nosql.py`. Esa funcion declara el GSI al crear la tabla y lo agrega si encuentra una tabla existente sin el indice, de modo que `make setup` converge al mismo esquema en ejecuciones repetidas. Los fixtures de inicializacion son sinteticos.

## Consistencia, despliegue y seguridad

- Las consultas por la clave primaria pueden solicitar lectura fuertemente consistente cuando el caso lo requiera. DynamoDB no admite lecturas fuertemente consistentes en GSI; las consultas del indice son eventualmente consistentes.
- `event_type` puede tener baja cardinalidad y concentrar escrituras en una particion. El GSI satisface las consultas funcionales de M05, pero no demuestra escalabilidad para cargas AWS; para ese escenario se medira throttling y se evaluara particionamiento adicional.
- `make setup` inicia DynamoDB Local con Docker Compose e inicializa tabla, indice y fixtures sinteticos. AWS Academy Learner Lab puede configurarse con variables de entorno; `AWS_SESSION_TOKEN` es opcional. No se guardan credenciales ni tokens en el repositorio.
- Se mantienen los comandos de proyecto `make setup`, `make verify` y `make run`. Docker Compose es el respaldo local si Learner Lab no esta habilitado.

## Consecuencias

- Las consultas M05 por tipo e intervalo deben usar `event-type-occurred-at-index` con `Query`, no `Scan`.
- Todo evento que se consulte por ese indice debe incluir `event_type` y `occurred_at` con los tipos y el formato acordados.
- Los GSIs generan costo y tienen consistencia eventual; las pruebas locales verifican el contrato funcional, no las hipotesis de rendimiento AWS.

## Validacion pendiente

Registrar en `evidence/m05-document-store.json` la salida de `make setup`, `make verify` y `make run`, el estado activo del indice y el SHA exacto de la entrega. La evidencia de los cuatro casos de prueba se completa al integrar el trabajo de validacion y CRUD.