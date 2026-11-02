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
| Commit | `cc2078c4d5cc6ce206be5cf59b98b65c8c31e3cf` |

## Resultados de lectura

Fuente: `artifacts/m08-benchmark-report-baseline.json` (copia estable del modo
quick; `artifacts/m08-benchmark-results.json` se regenera en cada `make verify`).

| Escenario | Baseline p50 (ms) | Indexado p50 (ms) | Ratio p50 | Baseline p95 (ms) | Indexado p95 (ms) | Ratio p95 | Baseline items | Indexado items | Ratio items | Veredicto |
|---|---|---|---|---|---|---|---|---|---|---|
| Página 1 | 90.9 | 5.3 | 17.1× | 115.7 | 6.5 | 17.9× | 72 000 | 1 040 | 69.2× | mejora observada |
| Página profunda (10) | 93.4 | 5.6 | 16.7× | 120.9 | 6.8 | 17.7× | 72 000 | 1 040 | 69.2× | mejora observada |
| Walk (10 páginas) | 942.3 | 51.5 | 18.3× | 1 112.2 | 65.0 | 17.1× | 720 000 | 10 400 | 69.2× | mejora observada |

### Interpretación

La línea base siempre lee **toda la partición** del juego caliente (1 800 ítems)
en cada consulta, sin importar qué página se solicite. El índice lee
`limit + 1 = 26` ítems por página, lo que reduce las lecturas 69× y la
latencia observada entre 17× y 18× dependiendo del escenario en esta corrida.

El veredicto lo calcula el script automáticamente: "mejora observada" cuando
el p95 y los items leídos del indexado son menores que los del baseline.

## Costo de escritura

| Métrica | Baseline (1 GSI) | Indexado (2 GSIs) | Delta |
|---|---|---|---|
| p50 (ms) | 4.0 | 4.0 | +0.03 ms |
| p95 (ms) | 5.3 | 5.9 | +0.6 ms |
| Muestras | 100 | 100 | — |

En DynamoDB Local la diferencia de latencia de escritura observada es pequeña,
pero no se realizó una prueba de significancia estadística. En AWS, cada GSI
con proyección ALL implica capacidad de escritura adicional (~1 WCU extra por
GSI proyectado por escritura) y duplica el almacenamiento del ítem proyectado.
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

6. **Sin prueba de significancia.** Las diferencias de latencia reportadas
   no se sometieron a prueba estadística (e.g. Mann-Whitney U). El gate
   de CI se basa en `itemsRead`, que es determinista.

7. **Duración del modo quick.** El plan interno proponía una meta de 90 s
   para el modo quick. En esta máquina la corrida tomó ~128 s. La
   diferencia se atribuye al entrelazado con warm-up sobre DynamoDB Local
   en Windows. El gate de CI no impone un límite de tiempo al benchmark;
   el timeout del workflow (20 min) es el único tope.

## Conclusión

El GSI `game-occurred-at-index` con paginación por cursor reduce las
lecturas de O(N) a O(limit) — en esta corrida, de 72 000 a 1 040 ítems
leídos por página (69.2×) — y elimina la inestabilidad del offset ante
inserciones concurrentes.

El trade-off es un atributo interno adicional, almacenamiento duplicado
en el GSI y consistencia eventual. El costo facturado en AWS (WCU, RCU,
almacenamiento) no se midió en esta corrida y requiere validación
adicional antes de adoptarse en producción.

## Ajustes respecto al plan

- **`artifacts/m08-benchmark-full.json`**: el plan preveía una corrida
  full (5× más iteraciones). No se generó en esta entrega porque la
  corrida completa toma ~10 min y no era un requisito del profesor.
  El artifact quick es suficiente para demostrar la corrección y el gate.
- **Duración quick ~128 s vs meta interna de 90 s**: la diferencia se
  documenta en la sección "Amenazas a la validez" punto 7.
