# ADR-003 - Seguridad relacional y minimo privilegio

## Estado

Aceptado.

## Contexto

M03 requiere separar las capacidades de migracion, escritura, lectura y operacion. Las contrasenas no deben quedar en SQL ni en archivos versionados.

## Decision

Se definen cuatro roles de aplicacion: `cdrl_migrator`, `cdrl_writer`, `cdrl_reader` y `cdrl_operator`. El migrador es propietario del esquema `public` y de las tablas de negocio para poder ejecutar DDL. El writer solo recibe `INSERT` y `UPDATE` en `games` y `game_metrics`, ademas del uso de sus secuencias; no recibe `DELETE`, `TRUNCATE` ni propiedad de tablas. El reader recibe `SELECT`; el operator recibe `pg_monitor` y no privilegios sobre tablas de negocio.

`REVOKE ALL ON SCHEMA public FROM PUBLIC` y revocaciones equivalentes sobre tablas y secuencias eliminan permisos heredados. Los privilegios por defecto del migrador conceden lectura a `cdrl_reader` para tablas futuras.

Las contrasenas se inyectan como variables de entorno al contenedor y el target `make security` las pasa como variables de `psql` mientras envia el SQL por stdin. El SQL no contiene contrasenas ni valores secretos. El script es idempotente para roles existentes mediante `ALTER ROLE` y para permisos mediante `GRANT`/`REVOKE`.

## Consecuencias

`make run` levanta PostgreSQL, ejecuta Alembic y aplica RBAC después de crear las tablas. Esto evita depender de mounts de archivos en `docker-entrypoint-initdb.d` y permite corregir permisos también en volúmenes existentes. El target `make security` puede repetirse desde una conexión administrativa.