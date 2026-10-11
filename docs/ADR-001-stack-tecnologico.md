# ADR 001: Selección del Stack Tecnológico

## Estado
Aceptado

## Contexto
El proyecto **Cloud Data Reliability Lab (CDRL)** requiere el desarrollo de una API para interactuar con bases de datos como parte de las actividades de la asignatura Bases de Datos en la Nube. Se necesita establecer un ecosistema de desarrollo ligero, moderno y que se acople perfectamente a contenedores, en lugar de utilizar frameworks monolíticos pesados que puedan añadir complejidad innecesaria. 

Además, se requiere definir explícitamente el contrato de datos mediante migraciones idempotentes, pruebas parametrizadas y un entorno reproducible.

## Decisión
Hemos decidido utilizar el siguiente conjunto de tecnologías para el backend:

* **Lenguaje:** Python 3.12
* **Backend / API:** FastAPI
* **Base de Datos (Relacional):** PostgreSQL
* **ORM:** SQLAlchemy
* **Migraciones:** Alembic
* **Testing:** pytest
* **Entorno Reproducible:** Docker Compose

## Justificación / Consecuencias

### Por qué FastAPI en lugar de Django
Se eligió **FastAPI** por ser un micro-framework mucho más ligero y enfocado en la construcción de APIs de alto rendimiento. Es más ligero que Django porque no necesitas todo el ecosistema de Django (admin, motor de plantillas, ORM estricto). FastAPI se integra nativamente con `Pydantic` para validación de datos (ideal para validar el contrato de datos en el Hito M01) y ofrece soporte asíncrono desde su núcleo.

### ORM y Migraciones
Al usar FastAPI, tenemos libertad para escoger el ORM. Elegimos **SQLAlchemy** por ser el ORM más maduro y potente de Python, lo que facilita enormemente el manejo de modelos de datos complejos. En conjunto usamos **Alembic**, la herramienta estándar de SQLAlchemy para generar migraciones idempotentes (script versionados de BD), cumpliendo directamente con los requerimientos del hito.

### Testing y Entorno
* **pytest** es el framework de pruebas de facto en Python, y facilita enormemente la escritura de pruebas parametrizadas (1 caso normal, 2 casos límite, 1 fallo declarado) solicitadas para validar la API.
* **Docker Compose** asegura que la base de datos (PostgreSQL), la aplicación y el entorno de pruebas puedan levantarse con un solo comando (`make run`), aislando el proyecto del entorno local y asegurando reproducibilidad (Persona 3).

### Consecuencias Negativas
* Al no ser un framework "todo incluido" como Django, el equipo debe integrar y configurar manualmente el enrutador (FastAPI), el ORM (SQLAlchemy) y las migraciones (Alembic), lo cual exige un poco más de trabajo inicial de arquitectura (Persona 1 y 2).
