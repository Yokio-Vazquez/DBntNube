# M08 — Correcciones de revisión de Persona 2

Cambios sobre el benchmark del commit `6758eb1a09ce0ea101d554fc71364d324d10df2d`.

## Espera de visibilidad

`_wait_for_index` reintenta hasta 60 veces si las páginas del GSI todavía no coinciden
con la tabla o si falta la página profunda. También reintenta una discrepancia en la
comprobación final. Si nunca converge, falla; los errores del servicio o configuración
no se ocultan. Entre intentos espera un segundo; los tiempos de las consultas se suman
a ese plazo, por lo que no es un timeout estricto de 60 segundos.

## Comparación de lecturas

La línea base (Query PK completo, sort y offset) y la propuesta (Query GSI con cursor)
consultan ahora la misma tabla física con ambos GSIs y los mismos documentos preparados
con `with_time_key`. Esto se aplica a correctitud, warm-up y los seis escenarios medidos.
La otra tabla, sin el GSI nuevo, se conserva para comparar latencia de escritura.

El artifact declara `readComparison` y `writeComparison` con las tablas efectivamente
usadas. `tables.baseline` y `tables.indexed` siguen identificando las dos tablas creadas;
para interpretar las mediciones de lectura debe usarse `readComparison`.

## Verificación local

Comando:

```text
python -m pytest tests/test_m08_benchmark_unit.py tests/test_m08_pagination_unit.py tests/test_m07_compat_read.py tests/test_m07_migrate_events.py tests/test_m06_document_versions.py -q -p no:cacheprovider
```

Resultado: **121 passed**, dos advertencias de dependencias; 24 pruebas del benchmark,
37 de paginación y 60 de compatibilidad M06/M07. Se cubren propagación tardía,
discrepancias temporales, plazo agotado, errores de servicio y separación de tablas
para lecturas/escrituras. Las tablas de estas pruebas son simuladas.

## Pendientes de medición real

El motor de Docker no respondió durante esta revisión. Siguen pendientes dos corridas
quick con igual dataset y elementos leídos, confirmar duración de quick menor a 90 s,
y la corrida full (`make bench`). No se generaron artifacts de rendimiento con mocks.
La disponibilidad de AWS Academy Learner Lab no está confirmada; no se realizó una
medición AWS. Persona 3 debe registrar el estado real del Lab en la evidencia.

Con DynamoDB Local operativo:

```text
python scripts/m08_benchmark.py --quick
make bench
```

No afirmar mejoras de rendimiento ni dar el hito por validado hasta medir y versionar
los resultados reales. Estas correcciones no cambian la autoría del trabajo original.
