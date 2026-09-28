.PHONY: setup verify run security

# Detecta automáticamente si el sistema usa 'python3' (Linux/Mac) o 'python' (Windows)
PYTHON := $(shell python3 --version > /dev/null 2>&1 && echo python3 || echo python)

setup:
	@$(PYTHON) -c "import os; [os.makedirs(d, exist_ok=True) for d in ['artifacts', 'evidence', 'docs', 'db/migrations', 'db/seed', 'src', 'tests']]"
	@$(PYTHON) -c "import os, sys; sys.exit(0 if os.path.isfile('.env.example') else 1)"
	@$(PYTHON) -c "import shutil, os; os.path.exists('.env') or shutil.copy('.env.example', '.env')"
	@docker compose up -d dynamodb
	@$(PYTHON) scripts/init_dynamodb.py
	@echo "CDRL starter base preparada. Configura .env localmente cuando corresponda."

verify:
	@$(PYTHON) scripts/verify_base.py

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
