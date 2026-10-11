# ADR 002: Modelo relacional operativo M02

## Estado
Aceptado

## Contexto
M01 registra juegos y mediciones, pero el catalogo de plataformas y la definicion de cada metrica estaban implicitos. Eso permitia repetir texto y dejaba la relacion entre un juego y sus plataformas fuera del esquema.

M02 debe conservar los datos de M01, rechazar combinaciones invalidas y permitir consultas parametrizadas para el flujo operativo del CDRL.

## Decision

- `platforms` es el catalogo unico de plataformas. `code` es la clave natural estable para cargas y consultas externas.
- `game_platforms` es una tabla puente con clave primaria compuesta. Evita duplicar una publicacion, conserva la fecha de salida y restringe el estado a `planned`, `available` o `retired`.
- `metric_definitions` es el catalogo de nombres y unidades permitidos. Una clave unica compuesta permite referenciar `(metric_name, unit)` desde `game_metrics` sin romper la API existente.
- Las claves foraneas usan `RESTRICT` para impedir borrar una plataforma o definicion que aun tenga datos dependientes. La relacion de publicacion a juego usa `CASCADE` porque la publicacion no tiene sentido sin su juego.
- Las tablas, indices y restricciones se crean con operaciones idempotentes. El bloque `DO` agrega la clave foranea de metricas solo cuando no existe.
- Los seeds usan `ON CONFLICT DO NOTHING`, por lo que pueden ejecutarse mas de una vez sin duplicar datos.

## Invariantes

1. Una plataforma no puede tener codigo, nombre o fabricante vacios.
2. Un juego solo puede tener una fila por plataforma.
3. Una publicacion no puede usar un estado desconocido ni una fecha anterior a 1970-01-01.
4. Una medicion solo puede usar una definicion registrada; por tanto `duration` usa `hours` y `rating` usa `stars`.
5. Las restricciones de rango de M01 siguen aplicando a las mediciones.

## Consultas y casos

Las consultas parametrizadas viven en `db/queries/002_parametrized_relational_queries.sql`. Cubren filtrado normal por plataforma y rating, un resultado vacio por rangos sin coincidencias y limites inclusivos mediante `BETWEEN`. El fallo declarado es intentar insertar una publicacion con estado `paused`: PostgreSQL debe rechazarla con `game_platforms_status_valid`.

## Consecuencias

El modelo agrega integridad en la base y permite extender catalogos sin modificar la tabla `games`. Se mantiene el nombre de las columnas de metricas de M01 para conservar compatibilidad con la API. La clave foranea compuesta requiere que las definiciones se carguen antes de insertar nuevas mediciones.
