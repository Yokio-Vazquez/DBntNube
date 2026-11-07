# Persona 3 · Pruebas, evidencia y entrega

Tu entrega incluye pruebas reproducibles en `tests/`, el resultado de la ejecución en `artifacts/`, el archivo correspondiente en `evidence/` y la entrega de Classroom. Parte de `tests/test_event_access.py` y acuerda con Persona 2 cómo consultar los registros.

| Caso | Acción | Comprobación |
|---|---|---|
| Normal | Crear como escritor un evento sintético con clave única y consultarlo como lector mediante GET /events y GET /events/page. | POST devuelve 201. Ambas consultas devuelven 200 y permiten recuperar la clave. |
| Límite de lectura | Consultar el evento existente sin credencial, incluidas las páginas. | Ambas rutas devuelven 401 y sus respuestas omiten el contenido del evento. |
| Límite de escritura | Intentar crear una clave nueva con la credencial del lector. | POST devuelve 403. Una consulta autorizada posterior confirma que la clave sigue ausente. |
| Fallo declarado | Configurar temporalmente la misma credencial sintética para lector y escritor en un entorno de prueba aislado e intentar crear. | POST devuelve 401 y no crea el documento. Restablecer el entorno al terminar. La prueba pasa al observar el fallo esperado. |

1. **Prepara la ejecución.** Usa fixtures sintéticos, genera credenciales efímeras y configura el entorno mediante variables. Usa AWS Academy Learner Lab si está habilitado y Docker Compose como respaldo. Documenta el entorno utilizado. Aísla los datos de cada corrida para que repetirla no produzca conflictos.
2. **Comprueba la auditoría en cada caso.** Captura los registros de esa prueba y compara actor, acción, recurso y resultado con el contrato de Persona 2. Comprueba la ausencia del marcador sintético sensible en registros, reportes y evidencia. Ejecuta también la regresión que demuestra la remediación.
3. **Automatiza el reporte.** Integra los casos en `make verify`. Genera un JSON en `artifacts/` con identificador de caso, esperado, observado y estado calculado a partir de la ejecución. Una comprobación fallida debe dejar el comando con salida distinta de cero. Usa el identificador y el esquema exigidos por el instructor para el archivo de `evidence/`. Consulta el hito anterior como referencia y enlaza resultados, reporte de remediación y SHA de cada contribución técnica.
4. **Valida desde un checkout limpio.** Ejecuta, en orden, `make setup`, `make verify` y `make run`. Conserva la salida de verify, revisa que esté libre de secretos y confirma que los archivos entregables se abren desde GitHub. Registra tus pruebas y scripts con tu propia identidad Git.
5. **Cierra la entrega antes del plazo.** Publica el tag semanal aprobado por el equipo sobre el commit validado. Obtén el SHA completo con `git rev-list -n 1 <tag>` y compáralo con el que muestra GitHub. Entrega en Classroom la URL del repositorio, el tag, ese SHA, la salida de `make verify` y la evidencia. Comprueba que Classroom muestra la entrega realizada antes del cierre.

Para la defensa oral, prepara la ejecución de un caso denegado y muestra cómo verificaste tanto el estado de la colección como el evento de auditoría.
