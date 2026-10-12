# ADR 006: Auditoría append-only y borrado lógico

## Estado
Aceptado

## Contexto

Las operaciones relevantes necesitan evidencia de quién las solicitó, qué recurso afectaron, cuándo ocurrieron y si tuvieron éxito. Los registros no deben copiar contraseñas, tokens ni otros secretos enviados junto con una solicitud. El rol `cdrl_writer` no tiene permisos directos de lectura ni borrado sobre las tablas de negocio.

## Decisión

- La tabla PostgreSQL `audit_logs` conserva actor, acción, recurso, resultado, fecha del servidor y detalles JSONB. Un trigger rechaza `UPDATE` y `DELETE`; el rol de aplicación solo recibe permiso `INSERT` y uso de la secuencia.
- El borrado de métricas es lógico: `soft_delete_metric(bigint)` marca `deleted_at` y solo permite al rol escritor ejecutar esa operación acotada. Las consultas de métricas excluyen filas marcadas, mientras la fila original y su historial se conservan.
- El evento de auditoría se inserta en la misma transacción que el borrado lógico. Si cualquiera de las dos operaciones falla, no se confirma ninguna.
- `record_audit` aplica una lista de campos sensibles a los detalles antes de persistirlos. No se serializa automáticamente el cuerpo HTTP completo. Los valores de contraseñas, tokens, secretos, credenciales, autorizaciones, claves API y claves privadas se reemplazan por `[REDACTED]`.
- `X-Actor-ID` permite asociar un identificador al evento. Como la API aún no implementa autenticación, ese valor identifica al actor declarado por el cliente y no constituye prueba de identidad.

## Consecuencias

La auditoría y los registros borrados permanecen disponibles para investigación, y la aplicación no obtiene permisos generales de borrado ni lectura. La recuperación es operativa mediante la fila conservada (restaurando `deleted_at` con `cdrl_migrator` o un administrador autorizado); no existe todavía un endpoint de restauración. El trigger protege contra cambios ordinarios de filas, pero un propietario o administrador de base de datos puede modificar el esquema o deshabilitarlo, por lo que la protección no equivale a almacenamiento WORM externo.

La migración Alembic `c84f39d2a611` instala la tabla, el trigger y la función SQL. Los permisos se aplican mediante `db/migrations/003_enforce_role_privileges.sql` y el procedimiento habitual de seguridad.