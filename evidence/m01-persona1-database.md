# Evidencia Persona 1: Base de datos

## Trabajo realizado

- Creación de la tabla `games`.
- Creación de la tabla `game_metrics`.
- Relación mediante `game_metrics.game_id`.
- Restricciones de unicidad y validación.
- Seed sintético con videojuegos AAA para consola.

## Archivos implementados

- `db/migrations/001_create_games_and_metrics.sql`
- `db/seed/001_seed_games_and_metrics.sql`

## Reglas verificadas

- `games.title` no acepta duplicados.
- `game_metrics.external_id` no acepta duplicados.
- `game_metrics.game_id` debe existir.
- `rating` debe estar entre `0` y `5`.
- `duration` debe ser mayor que `0`.
- `rating` usa la unidad `stars`.
- `duration` usa la unidad `hours`.

## Resultado

- Migración ejecutada correctamente.
- Migración ejecutada nuevamente sin errores.
- Seed ejecutado correctamente.
- Seed ejecutado nuevamente sin duplicar registros.
- Total esperado: 9 juegos y 18 métricas.

## Commit

SHA: completar después del commit.