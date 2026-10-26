.PHONY: setup verify run serve security migrate rollback

# Flujo oficial (100% automático, sin pasos manuales):
#   make setup   -> entorno virtual + dependencias + Docker + migraciones + roles
#   make verify  -> evidencias, disaster recovery, demo M07 y suite pytest
#   make run     -> ruta crítica: BD, API (arranca, se prueba y se detiene) y ciclo M07

ifeq ($(OS),Windows_NT)
SYS_PYTHON := python
VENV_PY := .venv\Scripts\python.exe
VENV_CHECK := .venv/Scripts/python.exe
else
SYS_PYTHON := $(shell command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
VENV_PY := .venv/bin/python
VENV_CHECK := .venv/bin/python
endif

# Usa el entorno virtual creado por 'make setup'; si no existe, el Python del sistema.
PYTHON := $(if $(wildcard $(VENV_CHECK)),$(VENV_PY),$(SYS_PYTHON))

setup:
	@echo "=> Preparando estructura y .env..."
	@$(SYS_PYTHON) -c "import os; [os.makedirs(d, exist_ok=True) for d in ['artifacts', 'evidence', 'docs', 'db/migrations', 'db/seed', 'src', 'tests']]"
	@$(SYS_PYTHON) -c "import os, sys; sys.exit(0 if os.path.isfile('.env.example') else 1)"
	@$(SYS_PYTHON) -c "import shutil, os; os.path.exists('.env') or shutil.copy('.env.example', '.env')"
	@echo "=> Creando entorno virtual .venv e instalando dependencias..."
	@$(SYS_PYTHON) -m venv .venv
	@$(VENV_PY) -m pip install --disable-pip-version-check -q -r requirements.txt
	@echo "=> Levantando PostgreSQL y DynamoDB Local..."
	@docker compose up -d --wait
	@echo "=> Inicializando DynamoDB, roles y migraciones..."
	@$(VENV_PY) scripts/init_dynamodb.py
	@$(VENV_PY) scripts/apply_security.py
	@$(VENV_PY) -m alembic upgrade head
	@$(VENV_PY) scripts/apply_security.py
	@echo "=> Setup completado."

verify:
	@echo "=> Ejecutando verificación completa..."
	@$(PYTHON) scripts/disaster_recovery.py
	@$(PYTHON) scripts/m07_demo.py
	@$(PYTHON) scripts/verify_base.py
	@$(PYTHON) -c "import pathlib; pathlib.Path('artifacts/test_report.xml').unlink(missing_ok=True)"
	@$(PYTHON) -m pytest tests/ -v --junitxml=artifacts/test_report.xml

run:
	@echo "=> Asegurando servicios y esquema..."
	@docker compose up -d --wait
	@$(PYTHON) scripts/init_dynamodb.py
	@$(PYTHON) scripts/apply_security.py
	@$(PYTHON) -m alembic upgrade head
	@$(PYTHON) scripts/apply_security.py
	@echo "=> Ejecutando ruta crítica del sistema CDRL..."
	@$(PYTHON) scripts/run_critical_path.py

# Opcional: deja la API escuchando de forma interactiva (bloquea la terminal).
# Usa el puerto 8080 porque DynamoDB Local ocupa el 8000.
serve:
	@$(PYTHON) -m uvicorn src.main:app --host 127.0.0.1 --port 8080

security:
	@$(PYTHON) scripts/apply_security.py

migrate:
	@$(PYTHON) scripts/migrate_events.py

rollback:
	@$(PYTHON) scripts/migrate_events.py --rollback
