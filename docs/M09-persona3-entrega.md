# Entrega Persona 3 · Pruebas, evidencia y resultados M09

**Hito:** M09 — Controles de acceso por colección y auditoría  
**Responsable:** Persona 3 (Salomón Álvarez Gómez · DevOps / QA / Entrega)  
**Fecha:** 8 de noviembre de 2026  

---

## 1. Alcance y entregables

Conforme al plan acordado en `docs/plan-equipo-controles-por-coleccion.md` y la guía `docs/M09-persona3-pruebas-entrega.md`, la entrega de Persona 3 integra y valida:

1. **Pruebas reproducibles en `tests/`:**
   - `tests/test_event_access.py`: cubre los 4 casos exigidos (Normal, Límite lectura, Límite escritura, Fallo declarado), la comprobación de los 4 campos obligatorios de auditoría y la ausencia de marcadores sintéticos sensibles.
   - `tests/event_test_client.py`: añade `WriterClient` junto con `ReaderClient` para aislar pruebas con sesiones de auditoría en memoria.
2. **Script de verificación y generación de artefactos (`scripts/verify_m09_controls.py`):**
   - Ejecuta de forma determinista los 4 casos y sus aserciones.
   - Genera `artifacts/m09-collection-controls-results.json` y `artifacts/m09-controles-coleccion-results.json`.
   - Verifica la ausencia del marcador sensible en registros y reporte.
   - Retorna código 0 en éxito y 1 en falla.
3. **Integración en `make verify` y `scripts/verify_base.py`:**
   - `Makefile` ejecuta `scripts/verify_m09_controls.py` como parte de `make verify`.
   - `scripts/verify_base.py` valida la presencia de archivos, el esquema de evidencia y el estado de los artefactos M09.
4. **Archivo de evidencia (`evidence/m09-collection-controls.json` y `evidence/m09-controles-coleccion.json`):**
   - Registra los tres integrantes con sus roles, archivos y commit SHAs completos.
   - Documenta los 4 casos, la verificación de auditoría, la remediación de Persona 2 y las limitaciones.

---

## 2. Demostración de los cuatro casos requeridos

| Caso | Acción ejecutada | Criterio esperado | Resultado observado | Auditoría observada (`actor_id`, `action`, `resource_type`, `outcome`) | Estado |
|---|---|---|---|---|---|
| **Normal** | POST `/events` como escritor con clave única; consulta posterior como lector mediante `GET /events` y `GET /events/page`. | POST devuelve 201. Ambas consultas devuelven 200 y recuperan la clave del evento. | 201 en POST; 200 en `GET /events`; 200 en `GET /events/page`. Clave recuperada en ambas rutas. | 1. `writer`, `create`, `events`, `success`<br>2. `reader`, `read`, `events`, `success`<br>3. `reader`, `read`, `events`, `success` | **PASSED** |
| **Límite 1 · Lectura** | Consultar evento existente sin credenciales mediante `GET /events` y `GET /events/page`. | Ambas rutas devuelven 401; la respuesta omite el contenido del evento. | 401 en ambas consultas. Cuerpo omite claves, atributos y contenido documental. | 1. `anonymous`, `read`, `events`, `denied`<br>2. `anonymous`, `read`, `events`, `denied` | **PASSED** |
| **Límite 2 · Escritura** | Intentar crear una clave nueva usando la credencial de solo lectura (`reader`). | POST devuelve 403. Una consulta autorizada confirma que la clave sigue ausente. | POST responde 403 ("Operación no permitida"). Consulta autorizada posterior confirma que la clave nunca se insertó. | 1. `reader`, `create`, `events`, `denied`<br>2. `reader`, `read`, `events`, `success` (verificación de ausencia) | **PASSED** |
| **Fallo declarado** | Configurar temporalmente la misma credencial para lector y escritor (`EVENTS_READER_TOKEN == EVENTS_WRITER_TOKEN`) e intentar crear. | POST devuelve 401 (la política deniega por ambigüedad/fail-closed) y no crea el documento. | POST responde 401 ("Credencial inválida"). Clave ausente en almacenamiento. Entorno restaurado al finalizar. | `anonymous`, `create`, `events`, `denied` | **PASSED** |

---

## 3. Contrato de auditoría y exclusión de secretos

### Cuatro campos obligatorios
En cada una de las operaciones evaluadas, se comprueba que el registro en `public.audit_logs` contenga los cuatro campos canónicos acordados con Persona 2:
- `actor_id`: `writer`, `reader` o `anonymous`.
- `action`: `create` o `read`.
- `resource_type`: exactamente `events`.
- `outcome`: `success`, `denied`, `conflict`, `unavailable` o `failure`.

### Exclusión de marcadores sintéticos sensibles
Para comprobar que no se copian cabeceras, tokens ni secretos al registro de auditoría ni al reporte:
1. Se inyectó una cabecera HTTP sensible con un identificador sintético único: `X-Synthetic-Header-Secret: SENSITIVE_SECRET_MARKER_<uuid>`.
2. Se comprobó que dicho marcador **NO** aparece en ninguna fila de `audit_logs` ni en sus parámetros SQL.
3. Se comprobó que el marcador **NO** forma parte de los artefactos JSON ni del archivo de evidencia.

---

## 4. Vinculación con la remediación de Persona 2

- **Desviación remediada por Persona 2:** Ausencia de registro de auditoría al denegar una creación a la identidad `reader` (rechazo 403 antes del endpoint).
- **Commit de remediación:** `f0b0385a68f2e74b336933a114567a67536172de` (Diego de Jesús Huerta Barroso).
- **Prueba de regresión vinculada:** `test_reader_create_denial_is_audited_without_request_marker` en `tests/test_m09_event_audit.py` y `test_remediation_reader_create_denial_recorded` en `tests/test_event_access.py`.
- **Resultado:** La denegación a `reader` deja un registro inmediato en `audit_logs` con `outcome='denied'`, `action='create'`, `actor_id='reader'` y sin copiar marcadores ni secretos.

---

## 5. Trazabilidad de commits del equipo (M09)

| Integrante | Rol | Commits clave | Aportación técnica |
|---|---|---|---|
| **Persona 1** (Yokio Yosafat Vázquez Carrillo) | Autorización | `d64cefcf56b1e54fb05a216fe56cc525460d1c98`<br>`edf0313eb19d94ddf9e75a366bd6d404bc35dbfb` | ADR-009, dependencias `require_event`, roles `reader`/`writer`, actualización de rutas `/events` y `/events/page`. |
| **Persona 2** (Diego de Jesús Huerta Barroso) | Auditoría y remediación | `bd99aca381a99912864075071779b4110b0122c6`<br>`ea623d38645c719ef6d4822bc21f822ef45b597c`<br>`3c997a4c7cf3d3b762c452e82e850dafeac5e4d2`<br>`f0b0385a68f2e74b336933a114567a67536172de` | `record_event_audit`, outbox transaccional, reconciliador CLI, migraciones Alembic `a909e501` y `b41c7d8e2f90`, remediación de denegaciones. |
| **Persona 3** (Salomón Álvarez Gómez) | Pruebas, evidencia y entrega | *(Commit actual)* | Automatización de los 4 casos, `scripts/verify_m09_controls.py`, `tests/test_event_access.py`, integración en `make verify` y `scripts/verify_base.py`, evidencia y reporte. |

---

## 6. Comandos de validación y reproducción

Para validar el flujo completo desde un entorno limpio:

```bash
# 1. Preparación de entorno
make setup

# 2. Verificación completa (Disaster Recovery + M07 Demo + M08 Benchmark + M09 Controles + verify_base + pytest)
make verify

# 3. Ruta crítica del sistema CDRL
make run
```

Ejecución directa de la validación M09:

```bash
python scripts/verify_m09_controls.py
python -m pytest tests/test_event_access.py tests/test_m09_event_audit.py -v
```
