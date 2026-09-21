.PHONY: setup verify run security

# Detecta automáticamente si el sistema usa 'python3' (Linux/Mac) o 'python' (Windows)
PYTHON := $(shell python3 --version > /dev/null 2>&1 && echo python3 || echo python)

setup:
	@mkdir -p artifacts evidence docs db/migrations db/seed src tests
	@test -f .env.example
	@echo "CDRL starter base preparada. Configura .env localmente cuando corresponda."

verify:
	@$(PYTHON) scripts/verify_base.py

run:
	@docker compose up -d
	@echo "Esperando a la BD..." && sleep 3
	@alembic upgrade head
	@$(MAKE) security

security:
	@$(PYTHON) scripts/apply_security.py
