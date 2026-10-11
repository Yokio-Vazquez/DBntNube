# Evidencia Persona 3: Pruebas automáticas M02

## Trabajo realizado

- Creación de pruebas automáticas para el modelo relacional M02.
- Cobertura de los 4 casos exigidos: normal, vacío, límite y fallo declarado.
- Adición de modelos SQLAlchemy para las tablas nuevas (`Platform`, `GamePlatform`, `MetricDefinition`).
- Corrección del bug en la migración de Alembic (ruta incorrecta al archivo de seed).

## Archivos implementados

- `tests/test_m02_relational.py`
- `src/models.py` (modelos `Platform`, `GamePlatform`, `MetricDefinition`)
- `alembic/versions/b7c2d9e4f1a0_m02_relational_model.py` (corrección de ruta)

## Casos de prueba

| Caso | Test | Resultado |
|------|------|-----------|
| Normal | `test_m02_normal_query_games_by_platform_and_rating` | PASSED |
| Vacío | `test_m02_empty_no_metrics_for_nonexistent_game` | PASSED |
| Límite | `test_m02_boundary_game_platform_status_valid_values` | PASSED |
| Fallo declarado | `test_m02_failure_invalid_platform_status_rejected` | PASSED |

## Resultado global

- 12 tests ejecutados (M01 + M02), 12 passed, 0 failed.
- `make setup`: passed
- `make verify`: passed
- `make run`: passed

## Commit

SHA: bb0fb02ad36236a56bb5347e5a71f574edc5f111 (tag: week-02-final)
