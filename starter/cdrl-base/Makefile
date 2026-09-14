.PHONY: setup verify run

setup:
	@mkdir -p artifacts evidence docs db/migrations db/seed src tests
	@test -f .env.example
	@echo "CDRL starter base preparada. Configura .env localmente cuando corresponda."

verify:
	@bash scripts/verify_base.sh

run:
	@docker compose up -d
	@echo "Esperando a la BD..." && sleep 3
	@alembic upgrade head
