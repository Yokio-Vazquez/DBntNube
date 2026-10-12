# ADR-003 - Seguridad relacional y minimo privilegio

## Estado

Aceptado.

## Contexto

M03 requiere separar las capacidades de migracion, escritura, lectura y operacion. Las contrasenas no deben quedar en SQL ni en archivos versionados.

## Decision

Se definen cuatro roles de aplicacion: `cdrl_migrator`, `cdrl_writer`, `cdrl_reader` y `cdrl_operator`. El migrador es propietario del esquema `public` y de las tablas de negocio para poder ejecutar DDL. El writer solo recibe `INSERT` y `UPDATE` en `games` y `game_metrics`, ademas del uso de sus secuencias; no recibe `DELETE`, `TRUNCATE` ni propiedad de tablas. El reader recibe `SELECT`; el operator recibe `pg_monitor` y no privilegios sobre tablas de negocio.

`REVOKE ALL ON SCHEMA public FROM PUBLIC` y revocaciones equivalentes sobre tablas y secuencias eliminan permisos heredados. Los privilegios por defecto del migrador conceden lectura a `cdrl_reader` para tablas futuras.

Las contrasenas se inyectan como variables de entorno al contenedor y el target `make security` las pasa como variables de `psql` mientras envia el SQL por stdin. El SQL no contiene contrasenas ni valores secretos. La migracion aditiva `003_enforce_role_privileges.sql` revoca todo privilegio de tabla al writer y concede solo `INSERT`/`UPDATE` en `games` y `game_metrics`; el uso de secuencias se limita a las necesarias para identidades. Alembic se conecta como `cdrl_migrator`, dueño del esquema y de las tablas.

## Rotación de Secretos

Solo el usuario administrador de bootstrap (`POSTGRES_USER`, `cdrl_dev`) tiene el atributo `CREATEROLE` en PostgreSQL y puede ejecutar `ALTER ROLE ... WITH PASSWORD ...`. `cdrl_migrator` es propietario del esquema y las tablas para DDL de negocio, pero **no tiene `CREATEROLE`** y no puede rotar las credenciales de otros roles.

Procedimiento de rotacion segura en produccion:
1. Generar la nueva contrasena de forma segura (gestor de secretos).
2. Conectarse a PostgreSQL con el usuario administrador (`POSTGRES_USER` / `cdrl_dev`).
3. Ejecutar: `ALTER ROLE cdrl_writer WITH PASSWORD 'nueva_contrasena';` (u otro rol).
4. Actualizar la variable de entorno en el orquestador de contenedores (ej. AWS Secrets Manager).
5. Redesplegar los contenedores de la API de forma escalonada para que tomen la nueva variable.

## Vista Operacional Segura

La vista `public.v_operational_summary` (owner: `cdrl_migrator`) expone totales de metricas y la ultima fecha de medicion por juego. El rol `cdrl_operator` tiene `SELECT` unicamente sobre esa vista; sus permisos de tabla siguen revocados. La migracion Alembic `d9f3a1b2e405` crea la vista y concede el permiso.

## Consecuencias

`make run` levanta PostgreSQL, prepara los roles, ejecuta Alembic como `cdrl_migrator` y vuelve a aplicar privilegios para cubrir las tablas recién creadas. Esto evita depender de mounts de archivos en `docker-entrypoint-initdb.d` y permite corregir permisos también en volúmenes existentes. El target `make security` puede repetirse desde una conexión administrativa.