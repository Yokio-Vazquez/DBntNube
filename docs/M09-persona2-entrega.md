# Entrega Persona 2: auditoría de eventos M09

## Alcance

Se agregó auditoría para `GET /events`, `GET /events/page` y `POST /events`,
incluidos los rechazos de autenticación y permisos que ocurren antes de ejecutar
los endpoints. Los resultados distinguen `success`, `denied`, `conflict`,
`unavailable` y `failure`.

El registro usa la identidad que resuelve el servidor (`reader` o `writer`) y
`anonymous` cuando falla la autenticación. Solo guarda actor, acción, tipo e ID
del recurso y resultado; no copia cabeceras, cuerpo ni mensajes crudos de error.
El registro se confirma antes de responder, y un fallo al persistirlo no se
presenta como éxito.

Para `POST /events`, se usa un outbox transaccional para no perder la auditoría
si DynamoDB crea el documento y luego falla PostgreSQL:

1. Se confirma en PostgreSQL una intención pendiente que contiene la identidad,
   `game_id`, `event_key` y un ID de operación aleatorio. No guarda el cuerpo.
2. Ese ID se adjunta al documento de DynamoDB como atributo interno y no se
   incluye en la respuesta pública.
3. La auditoría final y el cambio del outbox a completado se confirman juntos
   en una sola transacción PostgreSQL.
4. Si el paso final falla, la intención permanece pendiente. Se puede recuperar
   ejecutando `python scripts\reconcile_event_audit.py`; el proceso revisa
   operaciones con al menos cinco minutos de antigüedad, hace una lectura
   consistente de DynamoDB y registra `success` si coincide el ID de operación,
   `conflict` si existe otro documento con esa clave, o `unavailable` si no
   existe. Si alguno de los servicios sigue fallando, la fila queda pendiente
   para el siguiente intento.

## Cambios realizados

- `src/audit.py`: añade `record_event_audit`, valida los valores permitidos,
  limita el recurso a `events`, administra el ciclo de vida del outbox y
  completa atómicamente el registro final.
- `src/event_access.py`: registra los rechazos 401 y 403.
- `src/main.py`: registra el resultado de las lecturas; `POST /events` confirma
  la intención antes de escribir en DynamoDB y completa o deja recuperable la
  auditoría de la creación.
- `src/models.py`, `db/migrations/005_event_audit_outbox.sql` y
  `alembic/versions/b41c7d8e2f90_event_audit_outbox.py`: definen y migran el
  outbox protegido por permisos de `cdrl_writer`.
- `src/nosql.py`: añade el ID de correlación interno al crear un evento y
  permite lecturas consistentes para la reconciliación.
- `scripts/reconcile_event_audit.py`: reintenta completar auditorías pendientes
  sin exponer claves ni mensajes de error.
- `alembic/versions/a909e501_m09_event_audit_outcomes.py`: actualiza el
  constraint de resultados. El downgrade se detiene si ya hay resultados M09
  que el constraint anterior no permitiría.
- `db/migrations/004_audit_and_soft_delete.sql`: mantiene el constraint SQL
  sincronizado con los resultados admitidos.
- `tests/test_m09_event_audit.py`, `tests/test_event_access.py` y
  `tests/event_test_client.py`: comprueban denegaciones, rutas exitosas,
  resultados distintos para conflicto e indisponibilidad, fallo de auditoría
  posterior a la creación, recuperación del outbox, orden durable antes de
  DynamoDB y ausencia de filtración de marcadores internos.

## Pruebas y evidencia

La prueba de regresión para una creación denegada al rol `reader` se ejecutó
antes del cambio y detectó que faltaba el registro de auditoría. Después de la
implementación, esa prueba quedó cubierta por
`test_reader_create_denial_is_audited_without_request_marker`.

Comando de validación ejecutado:

```powershell
python -m pytest tests\test_m09_event_audit.py tests\test_event_access.py tests\test_m06_audit.py tests\test_m06_document_versions.py tests\test_m07_compat_read.py tests\test_m08_pagination_unit.py tests\test_m05_documental.py tests\test_main.py::test_get_events_queries_by_game tests\test_main.py::test_event_audit_override_is_removed_after_request tests\test_main.py::test_create_metric_does_not_return_generated_id -q --maxfail=1
```

Resultado: **102 pruebas aprobadas**. Se observaron dos advertencias de
deprecación de dependencias de prueba. También pasaron `compileall` para los
archivos modificados y `git diff --check`. La prueba
`test_created_event_with_failed_audit_commit_is_reconciled` simula un fallo del
commit final después de crear en DynamoDB y comprueba que la intención pendiente
se puede completar con el ID correlacionado.

Las pruebas usan una sesión de auditoría simulada. No se validó la migración ni
la consulta de registros contra una instancia real de PostgreSQL/DynamoDB, por
lo que esa verificación queda pendiente de un entorno de integración disponible.

## Contrato de consulta para Persona 3

Los registros se almacenan en `public.audit_logs`. Ejemplo para revisar las
auditorías de eventos:

```sql
SELECT id, actor_id, action, resource_type, resource_id, outcome, details, occurred_at
FROM public.audit_logs
WHERE resource_type = 'events'
ORDER BY id DESC;
```

Ejemplo saneado del contrato: `actor_id=reader`, `action=create`,
`resource_type=events`, `outcome=denied`. Las credenciales y los valores de
cabeceras no forman parte del registro.

## Estado de entrega

La implementación inicial se publicó en los commits `bd99aca` y `ea623d3`.
El outbox y su reconciliador son cambios posteriores todavía no confirmados en
un commit. La aplicación de ambas migraciones en PostgreSQL real y la
verificación extremo a extremo con DynamoDB siguen pendientes de un entorno de
integración disponible.
