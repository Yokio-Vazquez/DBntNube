# ADR-008 — Índice cronológico, paginación por cursor y rendimiento

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-11-01 |
| Autores | Equipo 3 (Personas 1, 2, 3) |
| Superada por | — |

## Contexto

### Problemas detectados antes de M08

1. **Truncación silenciosa a 1 MB.** `query_events(game_id)` ejecutaba un solo
   `table.query` sin recorrer `LastEvaluatedKey`. Si la partición superaba 1 MB,
   DynamoDB devolvía un subconjunto de los ítems sin indicarlo al consumidor.

2. **Orden no cronológico.** El sort key de la tabla (`event_key`) sigue el
   formato `tipo#fecha#id`, de modo que el orden del índice primario no es
   cronológico. Para ordenar por `occurred_at` había que traer toda la partición
   y ordenar en Python.

3. **Sin paginación.** `GET /events` devuelve **toda** la partición del juego
   solicitado. A medida que crece, el costo de red y lectura aumenta
   linealmente; la respuesta no incluye mecanismo de avance parcial.

4. **Sin benchmark ni medición.** No existía un proceso reproducible para
   cuantificar el costo de las consultas ni comparar estrategias.

## Decisión

### Índice secundario global (GSI)

Se agrega `game-occurred-at-index` con:

- **HASH**: `game_id` (N)
- **RANGE**: `game_time_key` (S) — clave compuesta `occurred_at + "#" + event_key`
- **Proyección**: `ALL`

La clave compuesta `game_time_key` resuelve el problema de empates en
`occurred_at`: dos eventos con el mismo timestamp se distinguen por su
`event_key` (que es la sort key de la tabla y es única dentro de la
partición). Esto garantiza un orden total dentro del GSI.

### Paginación por cursor (keyset)

`GET /events/page` usa un cursor opaco (base64url de JSON con la versión,
`game_id`, `occurred_at` y `event_key`) en lugar de offset numérico.

El cursor se traduce a un `ExclusiveStartKey` de DynamoDB. Cada página lee
`limit + 1` ítems (lookahead): si llegan `limit + 1`, hay más páginas y el
cursor apunta al ítem `limit`; si llegan menos, `nextCursor = null`.

Si DynamoDB corta la respuesta por el límite de 1 MB (`LastEvaluatedKey`
presente con menos de `limit + 1` ítems), se continúa consultando hasta
completar el lote o agotar los datos.

### Contrato de estabilidad

1. Un documento que existía al iniciar el recorrido y no se borró aparece
   **exactamente una vez**.
2. Un documento insertado **más reciente** que la posición del cursor **no
   aparece** en las páginas siguientes.
3. Un documento insertado **más antiguo** puede aparecer como mucho una vez.
4. Los empates en `occurred_at` no producen duplicados ni pérdidas.
5. **No hay snapshot transaccional.** El GSI es eventualmente consistente;
   no admite `ConsistentRead`.

### Compatibilidad

- `GET /events` conserva su firma y comportamiento. Ahora recorre
  `LastEvaluatedKey` internamente (corrección de la truncación).
- `GET /events/page` es un endpoint nuevo; no modifica consumidores existentes.
- Las versiones públicas de los documentos (v1/v2/v3) no cambian. El
  atributo interno `game_time_key` se excluye de las respuestas de la API.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| **Offset** (`items[offset:offset+limit]`) | Inestable ante inserciones: desplaza todos los documentos posteriores, produciendo duplicados u omisiones. Además, el costo es O(N) porque siempre lee toda la partición para luego recortar en Python. |
| **LSI** (`occurred_at` como sort key local) | Requiere recrear la tabla: los LSI solo se definen al crearla. Migrar los datos interrumpiría el servicio. |
| **Proyección KEYS_ONLY / INCLUDE** | Reduce almacenamiento del GSI, pero obliga a un `GetItem` extra por cada ítem para obtener los campos que no se proyectaron. Aumenta la latencia y las RCU. |
| **Scan + FilterExpression** | Peor caso: lee la tabla completa y filtra en el servidor. No escala. |
| **Paginación con token firmado (HMAC)** | Agrega complejidad (gestión de secretos) sin beneficio claro: el cursor solo expone la posición dentro del juego solicitado y no es un mecanismo de autorización. |

## Trade-offs medidos

Los números provienen de `artifacts/m08-benchmark-results.json` (modo quick,
DynamoDB Local).

### Lectura: cursor vs offset

| Escenario | Baseline (offset) p50 | Indexado (cursor) p50 | Ratio p50 | Items leídos baseline | Items leídos indexado | Ratio items |
|---|---|---|---|---|---|---|
| Página 1 | 181.7 ms | 11.5 ms | 15.8× | 72 000 | 1 040 | 69.2× |
| Página profunda (10) | 179.4 ms | 10.8 ms | 16.6× | 72 000 | 1 040 | 69.2× |
| Walk (10 páginas) | 1 890.8 ms | 102.6 ms | 18.4× | 720 000 | 10 400 | 69.2× |

La línea base siempre lee toda la partición (1 800 ítems × 40 iteraciones = 72 000).
El índice lee solo `limit + 1` por página.

### Escritura: costo adicional del GSI

| Métrica | Baseline (1 GSI) p50 | Indexado (2 GSIs) p50 | Delta p50 |
|---|---|---|---|
| Escritura `put_item` | 14.8 ms | 15.2 ms | +0.4 ms |

En DynamoDB Local la diferencia no es significativa. **En AWS**, cada GSI con
proyección ALL duplica el almacenamiento del ítem y consume capacidad de
escritura adicional (aproximadamente 1 WCU extra por GSI proyectado por
escritura).

### Consistencia eventual

El GSI es **eventualmente consistente**. Un evento recién insertado puede no
aparecer en el índice durante un breve período (típicamente milisegundos en
AWS; variable en DynamoDB Local). No se admite `ConsistentRead` sobre GSIs.
El benchmark incluye una fase de espera de visibilidad antes de medir.

### Almacenamiento

La proyección ALL duplica cada atributo en el almacenamiento del GSI. Para
el dataset del curso (~3 000 eventos sintéticos) el costo es negligible.
En producción con volúmenes altos, considerar proyección INCLUDE con los
campos necesarios para la paginación.

### Ausencia de snapshot

No existe un aislamiento transaccional entre páginas. Si un documento se
borra o modifica entre dos consultas paginadas, el resultado reflejará el
estado actual del índice en ese momento. El cursor no garantiza una vista
congelada.

## Límites del cursor

- Longitud máxima del cursor: 4 096 caracteres.
- Clave compuesta `game_time_key` máxima: 1 024 bytes.
- El cursor no está firmado; es opaco pero no secreto.
- Solo se admite la versión `v: 1` del formato.

## Consecuencias

- Se corrige la truncación silenciosa en `query_events` y `query_events_by_type`.
- Las consultas paginadas leen O(limit) ítems en lugar de O(N).
- Se agrega un atributo interno (`game_time_key`) que los consumidores no ven.
- El `ensure_events_table` ahora agrega GSIs faltantes de forma incremental
  y hace backfill de la clave compuesta en documentos existentes.
- El gate de CI usa `itemsRead` (determinista) y no latencia (ruidosa).
