# ADR-002 - Pruebas del sistema

## Estado

Aceptado

## Decisión

Se realizarán pruebas automáticas para comprobar la API y la base de datos.

## Casos probados

1. Registrar una métrica válida.

2. Registrar un `rating` con valor `0` o `5`.
   Resultado esperado: operación aceptada.

3. Registrar una `duration` con valor `10000`.
   Resultado esperado: operación aceptada.

4. Usar un `game_id` inexistente.

5. Repetir un `external_id`.
   Resultado esperado: `409 Conflict`.

## Ejecución

```text
make setup
make verify
pytest
```

## Evidencias

- Pruebas en `tests/`.
- Resultados en `artifacts/`.
- Contrato en `evidence/m01-data-contract.json`.

## Consecuencia

Las reglas principales de la API y la base de datos quedan comprobadas y los
errores esperados quedan documentados.
