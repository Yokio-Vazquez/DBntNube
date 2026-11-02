# M08 — Reporte de rendimiento

## Método

| Parámetro | Valor |
|---|---|
| Dataset | 3 000 eventos sintéticos deterministas (semilla `20261031`) |
| Juegos | 5 (`game_id` 1–5), con el juego 1 recibiendo el 60 % de los eventos (1 800) |
| Empates | 150 eventos comparten el timestamp `2025-01-01T00:00:00Z` |
| Iteraciones (quick) | 40 muestras por escenario, 5 de warm-up descartadas |
| Entrelazado | Los seis escenarios se ejecutan en orden aleatorio con semilla para no favorecer a ninguno |
| Percentil | Nearest-rank (documentado en `percentile()`) |
| Correctitud previa | Las páginas 1 y 10 de ambas estrategias devuelven los mismos `event_key` en el mismo orden |
| Gate CI | `indexed_deep.itemsRead < baseline_deep.itemsRead` (determinista, no usa latencia) |

## Entorno

| Campo | Valor |
|---|---|
| Target | `dynamodb-local` |
| Imagen | `amazon/dynamodb-local:2.5.2` |
| Plataforma | Windows-11-10.0.26200-SP0 |
| Python | 3.13.7 |
| CPU | 8 núcleos |
| CI | No (corrida local) |
| Commit | `a161f49f68bff4eb48d42a91a18e9c830d216ae2` |

## Resultados de lectura

Fuente: `artifacts/m08-benchmark-results.json` (modo quick).

| Escenario | Baseline p50 (ms) | Indexado p50 (ms) | Ratio p50 | Baseline p95 (ms) | Indexado p95 (ms) | Ratio p95 | Baseline items | Indexado items | Ratio items | Veredicto |
|---|---|---|---|---|---|---|---|---|---|---|
| Página 1 | 181.7 | 11.5 | 15.8× | 361.2 | 17.5 | 20.7× | 72 000 | 1 040 | 69.2× | mejora observada |
| Página profunda (10) | 179.4 | 10.8 | 16.6× | 350.5 | 26.0 | 13.5× | 72 000 | 1 040 | 69.2× | mejora observada |
| Walk (10 páginas) | 1 890.8 | 102.6 | 18.4× | 3 850.3 | 142.4 | 27.0× | 720 000 | 10 400 | 69.2× | mejora observada |

### Interpretación

La línea base siempre lee **toda la partición** del juego caliente (1 800 ítems)
en cada consulta, sin importar qué página se solicite. El índice lee
`limit + 1 = 26` ítems por página, lo que reduce las lecturas 69× y la
latencia entre 14× y 27× dependiendo del escenario.

El veredicto lo calcula el script automáticamente: "mejora observada" cuando
el p95 y los items leídos del indexado son menores que los del baseline.

## Costo de escritura

| Métrica | Baseline (1 GSI) | Indexado (2 GSIs) | Delta |
|---|---|---|---|
| p50 (ms) | 14.8 | 15.2 | +0.4 ms |
| p95 (ms) | 21.7 | 25.9 | +4.3 ms |
| Muestras | 100 | 100 | — |

En DynamoDB Local la diferencia de latencia de escritura es marginal. En AWS,
cada GSI con proyección ALL implica capacidad de escritura adicional (~1 WCU
extra por GSI por escritura) y duplica el almacenamiento del ítem proyectado.
El costo facturado no se observa en esta corrida (`billingCostObserved: false`).

## Comparación de tablas

Ambas estrategias de **lectura** usan la misma tabla física
(`readComparison.samePhysicalTable: true`), con los mismos documentos preparados
con `with_time_key`. La tabla sin el GSI nuevo se reserva exclusivamente para
la comparación de **escritura**.

## Amenazas a la validez

1. **DynamoDB Local ≠ AWS.** El emulador Java ejecuta todo en un solo proceso
   JVM con almacenamiento en memoria. No hay red, no hay particionado real,
   no hay WCU/RCU. Las latencias absolutas no son representativas de AWS.

2. **Ruido de la máquina.** Las mediciones locales están sujetas a la carga
   del SO, GC de la JVM y variabilidad del scheduler. El warm-up y el
   entrelazado mitigan parte del ruido, pero no lo eliminan.

3. **Tamaño del dataset.** 3 000 eventos es un dataset pequeño. Con
   particiones más grandes el beneficio del índice crece, pero también
   pueden aparecer efectos de almacenamiento y throughput que no se
   manifiestan aquí.

4. **Una sola corrida.** Los resultados provienen de una corrida local.
   Para mayor confianza se necesitarían múltiples corridas en el entorno
   objetivo.

5. **AWS Academy Learner Lab.** No se ejecutó una medición en AWS porque
   el Lab no estaba habilitado al momento de la corrida. Los números de
   este reporte son exclusivamente de DynamoDB Local.

## Conclusión

El GSI `game-occurred-at-index` con paginación por cursor reduce
drásticamente las lecturas (de O(N) a O(limit)) y elimina la inestabilidad
del offset ante inserciones concurrentes. El trade-off es un atributo
interno adicional, almacenamiento duplicado en el GSI y consistencia
eventual. Para el caso de uso del curso (consultar eventos de un juego
ordenados cronológicamente), el beneficio supera ampliamente el costo.
