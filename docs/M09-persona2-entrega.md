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

## Cambios realizados

- `src/audit.py`: añade `record_event_audit`, valida los valores permitidos,
  limita el recurso a `events` y confirma la transacción de auditoría.
- `src/event_access.py`: registra los rechazos 401 y 403.
- `src/main.py`: registra el resultado de las lecturas y creaciones, incluidos
  conflicto, indisponibilidad y error de lectura.
- `alembic/versions/a909e501_m09_event_audit_outcomes.py`: actualiza el
  constraint de resultados. El downgrade se detiene si ya hay resultados M09
  que el constraint anterior no permitiría.
- `db/migrations/004_audit_and_soft_delete.sql`: mantiene el constraint SQL
  sincronizado con los resultados admitidos.
- `tests/test_m09_event_audit.py`, `tests/test_event_access.py` y
  `tests/event_test_client.py`: comprueban denegaciones, rutas exitosas,
  resultados distintos para conflicto e indisponibilidad, persistencia simulada
  y ausencia de filtración de un marcador de cabecera.

## Pruebas y evidencia

La prueba de regresión para una creación denegada al rol `reader` se ejecutó
antes del cambio y detectó que faltaba el registro de auditoría. Después de la
implementación, esa prueba quedó cubierta por
`test_reader_create_denial_is_audited_without_request_marker`.

Comando de validación ejecutado:

```powershell
python -m pytest tests\test_m09_event_audit.py tests\test_event_access.py tests\test_m06_audit.py tests\test_m06_document_versions.py tests\test_m07_compat_read.py tests\test_m08_pagination_unit.py -q --maxfail=1
```

Resultado: **93 pruebas aprobadas**. Se observaron dos advertencias de
deprecación de dependencias de prueba. También pasaron `compileall` para los
archivos modificados y `git diff --check`.

Las pruebas usan una sesión de auditoría simulada. No se validó la migración ni
la consulta de registros contra una instancia real de PostgreSQL, por lo que
esa verificación queda pendiente de un entorno de base de datos disponible.

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

Los cambios están en el árbol de trabajo y **no se han confirmado en un
commit**. Por ello todavía no hay un SHA que compartir; se puede proporcionar
después de confirmar los cambios. La aplicación de la migración en PostgreSQL
real y la verificación de consulta corresponden a la validación de integración.
