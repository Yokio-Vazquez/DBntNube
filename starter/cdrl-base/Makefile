.PHONY: setup verify run security

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
	@$(MAKE) security

security:
	@docker compose exec -T postgres sh -c 'psql --username "$$POSTGRES_USER" --dbname "$$POSTGRES_DB" --set=migrator_password="$$CDRL_MIGRATOR_PASSWORD" --set=writer_password="$$CDRL_WRITER_PASSWORD" --set=reader_password="$$CDRL_READER_PASSWORD" --set=operator_password="$$CDRL_OPERATOR_PASSWORD"' < db/migrations/002_roles_and_privileges.sql
