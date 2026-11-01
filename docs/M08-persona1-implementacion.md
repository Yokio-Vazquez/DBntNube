# M08 — Persona 1: índice, cursor y API

Implementación local sobre base `34d79545dee7a0c770653e4754d460d1b02e93a7`.
La autoría y los SHA de entrega se registran al integrar; este documento no declara benchmarks ni integración aprobada.

## Contratos para Personas 2 y 3

- Importar `GLOBAL_SECONDARY_INDEXES`, `ATTRIBUTE_DEFINITIONS`, `TABLE_KEY_SCHEMA` para crear tablas aisladas.
- GSI `game-occurred-at-index`: HASH `game_id`, RANGE `game_time_key`, proyección ALL.
- Preparar **cada documento** con `src.nosql.with_time_key(item)` antes de `put_item` o `batch_writer`.
  Este helper agrega el atributo interno `game_time_key = occurred_at + "#" + event_key`, sin mutar el original.
  La clave permite ordenar por `(occurred_at, event_key)` descendente incluso con fechas iguales.
- Fechas UTC canónicas `YYYY-MM-DDTHH:MM:SSZ`; la clave compuesta tiene máximo 1024 bytes.
- `query_events_page(game_id, limit, cursor=None, *, table=None)` devuelve `items`, `nextCursor`, `scannedCount`.
  No usa filtros; suma ScannedCount de todas las consultas de relleno y lookahead.
- `query_events` y `query_events_by_type` conservan firmas y agotan LastEvaluatedKey.
- `ensure_events_table` agrega los índices faltantes secuencialmente y espera ACTIVE; después recorre
  la tabla y actualiza claves internas faltantes/obsoletas. Ejecutar setup con escritores detenidos.
  El backfill es repetible y condicional: no recrea documentos eliminados ni pisa un timestamp cambiado.
- La API de escritura mantiene la clave al crear/actualizar y el seed también la incluye.
  Las escrituras directas externas deben usar el helper; de otro modo el GSI disperso omite el documento.
  Migración/rollback M07 preservan atributos adicionales existentes.

## API

`GET /events/page?game_id=1&limit=25&version=3&cursor=...`

Respuesta: `items`, `nextCursor`, `limit`, `order=occurred_at_desc`.
400 cursor inválido/de otro juego; 422 parámetros fuera de rango; 500 versión almacenada desconocida;
503 fallo de DynamoDB. Se normalizan/proyectan los documentos sin exponer la clave interna.
`GET /events` conserva su contrato público.

`EVENTS_PAGE_DEFAULT_LIMIT=25`, `EVENTS_PAGE_MAX_LIMIT=100`; deben cumplir
`1 <= default <= max <= 1000`. Configuración inválida impide importar/arrancar la API.

## Ajustes respecto al plan recibido

El GSI ordena por clave compuesta, en lugar de solo occurred_at. Incluir event_key únicamente en el cursor
no garantiza orden en los empates. Esto agrega un atributo interno de almacenamiento, sin cambiar las
versiones públicas de los documentos.

Cursor v1: base64url de JSON con v, game_id, occurred_at, event_key; ExclusiveStartKey incluye
las claves de tabla e índice. Se admite hasta 4096 caracteres (en lugar de 512), para poder representar
una clave de índice válida de hasta 1024 bytes y el resto del payload sin emitir cursores inutilizables.
El cursor es opaco para el consumidor, no está firmado y no es un mecanismo de autorización.

## Estabilidad y límites

Con documentos inicialmente visibles en el índice y claves de orden sin cambios, los originales no
eliminados se recorren una vez. Inserciones anteriores al cursor no aparecen después; inserciones
posteriores pueden aparecer una vez. No hay snapshot transaccional. Esperar visibilidad del GSI antes
de iniciar pruebas/benchmark en AWS; no admite lecturas fuertemente consistentes.
Cambios de fecha durante el recorrido quedan fuera de la garantía. No se afirma rendimiento medido.

## Verificación

`python -m pytest tests/test_m08_pagination_unit.py tests/test_m07_compat_read.py tests/test_m07_migrate_events.py tests/test_m06_document_versions.py -q`

Las pruebas unitarias usan tablas falsas, incluyendo cortes del servicio, lookahead, empates e inserciones.
No sustituyen las pruebas reales a cargo de Persona 3. La ruta crítica consulta dos páginas sin duplicados;
con el fixture de dos eventos usa limit=1 tras comprobar la consulta con limit=2.
La certificación final requiere `make setup`, `make verify`, `make run` y CI.

Resultado local: 97 pruebas aprobadas (37 M08 y 60 M06/M07), con dos advertencias de dependencias.
`git diff --check` sin errores. Docker Desktop se intentó iniciar, pero su motor no respondió;
no se ejecutaron pruebas de integración ni el flujo completo, ni se generó evidencia de entrega.
