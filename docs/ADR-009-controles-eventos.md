# Decisión de Persona 1 · Acceso a la colección de eventos

La colección documental publicada por la API corresponde a la tabla DynamoDB seleccionada mediante `DYNAMODB_TABLE` (por defecto `cdrl_events`). Los controles se aplican antes de llamar al adaptador de almacenamiento.

| Identidad de servicio | Consultar y paginar | Crear | Actualizar o borrar por HTTP |
|---|---|---|---|
| Lector | Permitido | 403 | Sin ruta |
| Escritor | Permitido | Permitido | Sin ruta |
| Sin credencial válida | 401 | 401 | Sin ruta |

Las consultas son `GET /events` y `GET /events/page`. La creación usa `POST /events` y devuelve 201, o 409 si ya existe la clave. El alta condicional preserva el documento existente. Las operaciones de mantenimiento directo de DynamoDB requieren administrar por separado el acceso al servicio. Las rutas relacionales conservan los roles PostgreSQL de hitos anteriores.

El operador inyecta secretos aleatorios distintos mediante `EVENTS_READER_TOKEN` y `EVENTS_WRITER_TOKEN`. El cliente envía el suyo mediante autorización HTTP Bearer, sobre HTTPS fuera del entorno local. Una variable ausente deshabilita esa identidad. Dos credenciales idénticas producen 401. La API determina el rol en el servidor. Para Persona 2, las identidades de servicio son reader y writer y las acciones son read y create.
