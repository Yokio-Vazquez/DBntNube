# Plan de trabajo del equipo · Controles por colección y operación

El hito estará listo cuando el equipo demuestre que una lectura y una escritura sin permiso se rechazan, que cada decisión deja un evento útil sin secretos y que una prueba de regresión verifica la remediación documentada.

| Responsable | Actividades y entregables | Cómo comprobar que terminó |
|---|---|---|
| Integrante 1 · Autorización | Inventariar las colecciones y sus operaciones en el ADR de `docs/`, empezando por los eventos que gestiona `src/nosql.py`. Acordar con el equipo una matriz de rol, colección, operación y decisión. Implementar la validación antes del acceso a datos en todas las rutas pertinentes, incluidas las consultas paginadas. Denegar por defecto. | Entregar código y configuración trazables a su commit. Con los fixtures del integrante 3, verificar que los permisos de lectura y escritura se conceden por separado y coinciden con la matriz. |
| Integrante 2 · Auditoría y remediación | Revisar `src/audit.py` e instrumentar las decisiones permitidas y denegadas. Construir eventos con una lista explícita de campos que incluya actor sintético, acción, recurso y resultado. Elegir una desviación concreta encontrada durante la revisión, aplicar la corrección con el integrante 1 si afecta permisos y documentar causa, cambio y prueba en el ADR. | Entregar implementación, una prueba de regresión propia y ejemplos saneados. Registrar el resultado observado de la prueba antes y después del arreglo. Verificar que cada evento identifica la operación sin copiar el cuerpo de la solicitud ni las variables de entorno. |
| Integrante 3 · Pruebas, resultados y entrega | Preparar fixtures sintéticos, automatizar los cuatro casos de la tabla e integrarlos en `make verify`. Generar un JSON en `artifacts/` con identificador, esperado, observado y estado por caso. Preparar el archivo correspondiente en `evidence/` siguiendo el formato del instructor y reunir los commits de los tres autores. | Ejecutar el flujo completo desde un checkout limpio. Abrir el JSON y comprobar que coincide con la salida de verificación. Entregar en Classroom los elementos indicados abajo. |

## Casos que el equipo debe demostrar

| Caso | Ejecución con datos sintéticos | Criterio observable |
|---|---|---|
| Normal | Un actor con permisos de escritura y lectura crea un evento y lo consulta. | Se recupera el evento esperado y ambas operaciones dejan registro de éxito. |
| Límite 1 · Lectura | Un actor sin permiso de lectura en la colección intenta consultar un evento que el fixture confirma que existe. | La operación se deniega sin revelar el documento. El evento de auditoría indica lectura denegada. |
| Límite 2 · Escritura | Un actor con permiso exclusivo de lectura intenta modificar ese evento. | La operación se deniega. Una lectura posterior autorizada confirma que el contenido sigue intacto. La auditoría registra la escritura denegada. |
| Fallo declarado | Un actor intenta operar con un rol que la política no reconoce. Declarar de antemano la denegación esperada. | El control falla de forma cerrada y la auditoría identifica el intento. La prueba pasa únicamente si observa el rechazo previsto. |

En cada caso, comprobar los cuatro campos obligatorios del evento. Usar un marcador sintético en un campo que deba excluirse y verificar su ausencia en los registros, el JSON y la evidencia. El integrante 2 debe vincular la remediación con el caso que la cubre o añadir una prueba específica.

## Secuencia y cierre

1. **Antes de implementar**, los tres acuerdan la matriz, los identificadores sintéticos y los resultados esperados. Trabajan en el repositorio GitHub del equipo creado desde la base del instructor, conservando su historia. Cada integrante registra con su propia cuenta los commits de su aportación técnica.
2. **Al integrar**, usar AWS Academy Learner Lab si está habilitado y Docker Compose como respaldo. Configurar el entorno mediante variables. Excluir credenciales, tokens, datos personales y cadenas de conexión del repositorio, las salidas y la evidencia.
3. **Antes de etiquetar**, el integrante 3 ejecuta `make setup && make verify && make run`, conserva la salida saneada de `make verify` y comprueba el arranque. El integrante 1 contrasta los resultados con la matriz y el integrante 2 revisa la auditoría y la prueba de remediación. Registrar el entorno realmente utilizado.
4. **Antes del cierre de Classroom**, publicar el tag semanal sobre el commit validado. Entregar URL del repositorio, tag, SHA exacto del commit al que apunta, salida de `make verify` y evidencia. Verificar que desde el tag se accede al código, configuración, scripts, pruebas, ADR, JSON y archivo de evidencia. Después del cierre la calificación es 0.

**Evaluación y defensa.** De los 8 puntos, 5.5 corresponden a evaluación automática, 2.0 a semiautomática y 0.5 a revisión manual. Para una posible defensa breve, cada integrante debe poder mostrar su commit y explicar una decisión con su prueba o evidencia.
