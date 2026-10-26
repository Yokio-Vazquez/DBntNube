# ADR 007: Evolución compatible de documentos (v3 aditiva)

## Estado
Aceptado

## Contexto

Desde M06, la tabla DynamoDB `cdrl_events` almacena documentos en dos formatos: v1 (sin campo `schemaVersion`, implícita) y v2 (`schemaVersion: 2`). Ambos comparten la misma estructura base (`game_id`, `event_key`, `event_type`, `occurred_at`, `source`); la diferencia es únicamente el número de versión. Se necesita enriquecer los documentos con campos nuevos (`platform`, `metadata`) sin romper a los consumidores existentes del API.

La tabla usa `game_id` (PK) y `event_key` (SK), con un GSI `event-type-occurred-at-index` sobre `event_type` + `occurred_at`. Renombrar o eliminar cualquiera de estos campos rompería el índice y las consultas existentes.

## Decisión

### Esquema v3 aditivo

La versión 3 agrega campos opcionales con default; no renombra ni elimina ninguno:

| Campo            | v1          | v2          | v3                              |
|------------------|-------------|-------------|----------------------------------|
| Campos base      | ✅          | ✅          | ✅ sin cambios                   |
| `schemaVersion`  | no existe   | `2`         | `3`                              |
| `platform`       | —           | —           | `"pc" \| "console" \| "mobile" \| "unknown"` |
| `metadata`       | —           | —           | mapa opcional, default `{}`      |
| `migratedFrom`   | —           | —           | `1` o `2` si viene de migración; ausente si se escribió directo |

### Lectura compatible (expand)

`normalize_event()` acepta v1, v2 y v3 simultáneamente. `GET /events` conserva la versión de cada documento tal cual está almacenado. Antes de migrar, los documentos v1/v2 no contienen campos de v3. Después de migrar, los documentos ya son v3 y la respuesta sin parámetro `version` incluye `platform`, `metadata` y `migratedFrom`. Los consumidores estrictos que no toleran campos nuevos deben solicitar `GET /events?version=2` para obtener una proyección sin los campos de v3.

Un parámetro opcional `GET /events?version=N` aplica proyección:
- `version=3` → todos los documentos se presentan como v3, con defaults para los campos faltantes.
- `version=2` o `version=1` → se omiten `platform`, `metadata`, `migratedFrom` y marcas internas.
- Fuera de rango → 422 (validado por FastAPI).
- Versión desconocida almacenada → 500 (comportamiento conservado de M06).

La proyección HTTP no modifica almacenamiento: un v3 nativo proyectado a v2 sigue siendo v3 en la tabla.

### Escritura configurable (`EVENT_WRITE_VERSION`)

La variable de entorno `EVENT_WRITE_VERSION` controla la versión de escritura:
- `2` (default): comportamiento idéntico al anterior; rechaza campos de v3.
- `3`: exige `platform` válido (`pc`, `console`, `mobile`, `unknown`); `metadata` es opcional con default `{}`. No acepta `migratedFrom` (reservado para migración).
- Cualquier otro valor produce un error al arrancar la aplicación.

Regresar la variable a `2` es el rollback de los escritores.

### Migración repetible (migrate)

El script `scripts/migrate_events.py` convierte documentos v1/v2 a v3:
- Agrega `platform="unknown"`, `metadata={}`, `migratedFrom=<versión original>` y `schemaVersion=3`.
- Conserva una marca interna `migratedVersionExplicit` para distinguir v1 implícita (sin `schemaVersion`) de v1 explícita (`schemaVersion: 1`), permitiendo una ida y vuelta exacta.
- Conserva atributos adicionales originales del documento.
- Usa `put_item` con `ConditionExpression` que verifica existencia y versión de origen.
- Documentos ya en v3 → se omiten (`skipped`).
- Condición fallida (otro proceso ya migró) → `skipped`.
- Documentos inválidos (versión desconocida, campos faltantes) → `failed`, sin modificar.
- La segunda ejecución reporta `migrated: 0`.

### Rollback selectivo

`scripts/migrate_events.py --rollback` revierte documentos con `migratedFrom`:
- Restaura la versión original y elimina los campos de v3 y las marcas de migración.
- v1 implícita se restaura sin `schemaVersion`; v1 explícita con `schemaVersion: 1`.
- v3 nativo (sin `migratedFrom`) → `skipped` (no tiene versión original).
- El rollback es global: revierte todos los documentos migrados, no solo el último lote.

### Scan paginado y snapshots

El scan usa `LastEvaluatedKey` para paginar. La verificación de idempotencia y rollback compara snapshots SHA-256 de la tabla completa (serialización canónica, independiente del orden de documentos y mapas, con normalización de `Decimal`).

## Reglas de compatibilidad

- ✅ **Permitido:** agregar campos opcionales con default.
- ❌ **Prohibido:** renombrar o eliminar `game_id`, `event_key`, `event_type`, `occurred_at` (llave/GSI); cambiar tipos de campos existentes; hacer obligatorio un campo viejo.
- ❌ **Prohibido:** que documentos antiguos contengan campos reservados de v3 o marcas de migración.

## Límites

- El rollback pierde `platform` y `metadata` de los documentos migrados, porque esos campos no existían en v1/v2.
- Los v3 nativos (escritos directamente en v3) no se pueden revertir: no tienen versión original.
- DynamoDB no tiene transacciones sobre toda la tabla: la migración es por documento y repetible, no atómica. Se deben detener todos los escritores y otros migradores durante la ejecución. Las condiciones comprueban existencia y versión, pero no detectan cambios concurrentes en otros atributos. Esta limitación se acepta como suficiente para el alcance actual.
- La fase *contract* (eliminar soporte de v1/v2) queda fuera de alcance.
- Ventana de transición: mientras exista algún documento v1/v2, el lector debe soportarlos.
- La compatibilidad aditiva presupone clientes que toleran campos nuevos; clientes estrictos deben solicitar `version=2`.
- `--dry-run` valida y cuenta operaciones previstas sin modificar datos; no demuestra idempotencia ni rollback.

## Consecuencias

Los consumidores existentes siguen funcionando sin cambios. La migración se puede ejecutar de forma segura con `make migrate` y revertir con `make rollback`. La verificación completa se ejecuta con `make verify`, que genera el artifact `artifacts/m07-migration-results.json` sobre una tabla aislada (`cdrl_events_m07_test`) y confirma `idempotent: true` y `rollbackVerified: true`.
