# M07 — Implementación de Persona 1

## Alcance completado

Lectura simultánea v1/v2/v3, proyección explícita del API, escritura configurable y funciones puras compartidas de conversión. No se ejecutaron migraciones ni se modificaron datos en PostgreSQL/DynamoDB.

| Archivo | Cambio |
| --- | --- |
| `src/event_schemas.py` | `EventV3`, `SUPPORTED_VERSIONS`, `detect_version`, `upcast_to_v3`, `downcast_from_v3`, `project`; lectura de las tres versiones. |
| `src/schemas.py` | Modelos de escritura v2/v3 y selección del alias público `EventDocument` mediante configuración. |
| `src/main.py` | Parámetro `version` opcional en `GET /events` y respuesta con las tres versiones. |
| `.env.example` | `EVENT_WRITE_VERSION=2` y explicación de activación. |
| `tests/test_m07_compat_read.py` | 43 casos parametrizados de compatibilidad, conversión, configuración y persistencia simulada. |

## Uso

- `GET /events?game_id=1`: conserva la versión de cada documento; las respuestas v1/v2 mantienen el contrato anterior.
- `GET /events?game_id=1&version=3`: devuelve todos como v3; los antiguos reciben `platform="unknown"` y `metadata={}`.
- `GET /events?game_id=1&version=2`: proyecta a v2 sin campos de v3 ni marcas internas, incluso para v3 nativo.
- `GET /events?game_id=1&version=1`: proyecta a v1 con `schemaVersion: 1`, como el contrato HTTP histórico.
- Una versión de consulta fuera de 1–3 devuelve 422. Una versión desconocida guardada devuelve 500.

Sin flag, la escritura es v2. Para activar v3, configurar `EVENT_WRITE_VERSION=3` y reiniciar el proceso. La selección ocurre al importar `src.schemas`; un valor distinto de `2` o `3` provoca un error claro antes de servir la aplicación. Los escritores v3 deben incluir `platform` (`pc`, `console`, `mobile` o `unknown`); `metadata` es un mapa con default independiente `{}`. No pueden enviar marcas de migración. La escritura v2 continúa rechazando campos nuevos. Los endpoints existentes de escritura de métricas SQL no cambian; `EventDocument` se utiliza en las funciones documentales de `src/nosql.py`.

## Contrato para Persona 2

Las firmas acordadas están disponibles en `src.event_schemas`. Las conversiones retornan copias profundas, no modifican el argumento y conservan atributos adicionales originales. Las versiones numéricas `Decimal` de DynamoDB están admitidas. Valores desconocidos, cadenas y booleanos como versión se rechazan.

`upcast_to_v3` valida los campos requeridos mediante el lector, agrega defaults y `migratedFrom`, y deja los v3 válidos sin cambios. Los documentos antiguos con campos reservados v3/migración se rechazan para evitar pérdidas. La escritura persistida usa `schemaVersion`; la migración rechaza el alias Python `schema_version`.

Marca interna adicional: `migratedVersionExplicit`. Se agrega a documentos provenientes de v1 para recordar si existía `schemaVersion: 1`. `downcast_from_v3` la elimina y restaura la presencia/ausencia original del campo. Si un v3 migrado de v1 anterior no tiene esa marca, se asume v1 implícita. No confundir esta marca con una identificación de lote.

`downcast_from_v3` solo admite v3 con `migratedFrom` igual a 1 o 2; v3 nativo provoca `ValueError`. El rollback sigue siendo global según la guía corregida. La proyección HTTP permite convertir v3 nativo a v2 porque no escribe en almacenamiento. Los modelos de respuesta omiten la marca interna de presencia; `migratedFrom` solo aparece cuando tiene valor.

Las funciones puras no resuelven concurrencia, paginación, escrituras condicionales, reportes o recuperación de una tabla: corresponden al script de Persona 2. La validación del lector conserva las reglas previas de M06; no equivale a la validación estricta de nuevas escrituras.

## Verificación realizada

Comando desde la raíz del repositorio:

```powershell
python -m pytest tests/test_m06_document_versions.py tests/test_m07_compat_read.py tests/test_m04_nosql.py tests/test_main.py::test_health_check tests/test_main.py::test_get_events_queries_by_game -q -p no:cacheprovider
```

Resultado: **53 aprobadas**, incluidas las cuatro M06, 43 M07, cuatro M04 y dos regresiones de la API. No necesitan Docker; las consultas y escrituras documentales usan mocks. Se emitieron dos advertencias de deprecación de dependencias de pruebas, sin fallos.

En este equipo, el aislamiento provocaba bloqueo del TestClient y una excepción nativa de Windows. La ejecución autorizada fuera del aislamiento completó estas pruebas. No se verificó la suite completa con servicios reales ni `make setup/verify/run`.

## Trabajo restante

Persona 2: migración/rollback de tabla, fixture y CLI. Persona 3: integración real aislada, ADR-007, evidencia, artifact y verificación completa. No se generaron artifacts de éxito para tareas pendientes. La publicación se realiza con la cuenta Yokio-Vazquez por indicación del usuario. No se crean tags de entrega M07 ni se atribuyen contribuciones a las Personas 2 y 3.
