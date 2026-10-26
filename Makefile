.PHONY: setup verify run security migrate rollback

# Detecta automáticamente si el sistema usa 'python3' (Linux/Mac) o 'python' (Windows)
PYTHON := $(shell python3 --version > /dev/null 2>&1 && echo python3 || echo python)

setup:
	@$(PYTHON) -c "import os; [os.makedirs(d, exist_ok=True) for d in ['artifacts', 'evidence', 'docs', 'db/migrations', 'db/seed', 'src', 'tests']]"
	@$(PYTHON) -c "import os, sys; sys.exit(0 if os.path.isfile('.env.example') else 1)"
	@$(PYTHON) -c "import shutil, os; os.path.exists('.env') or shutil.copy('.env.example', '.env')"
	@docker compose up -d --wait
	@$(PYTHON) scripts/init_dynamodb.py
	@$(MAKE) security
	@alembic upgrade head
	@$(MAKE) security
	@echo "Entorno CDRL preparado."

verify:
	@$(PYTHON) scripts/disaster_recovery.py
	@$(PYTHON) scripts/m07_demo.py
	@$(PYTHON) scripts/verify_base.py
	@$(PYTHON) -c "import pathlib; pathlib.Path('artifacts/test_report.xml').unlink(missing_ok=True)"
	@$(PYTHON) -m pytest tests/ --junitxml=artifacts/test_report.xml

run:
	@docker compose up -d
	@echo "Esperando a la BD..."
	@$(PYTHON) -c "import time; time.sleep(3)"
	@$(PYTHON) scripts/init_dynamodb.py
	@$(MAKE) security
	@alembic upgrade head
	@$(MAKE) security

security:
	@$(PYTHON) scripts/apply_security.py

migrate:
	@$(PYTHON) scripts/migrate_events.py

rollback:
	@$(PYTHON) scripts/migrate_events.py --rollback
