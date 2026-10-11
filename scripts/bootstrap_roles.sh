#!/usr/bin/env sh
set -eu

: "${CDRL_MIGRATOR_PASSWORD:?CDRL_MIGRATOR_PASSWORD is required}"
: "${CDRL_WRITER_PASSWORD:?CDRL_WRITER_PASSWORD is required}"
: "${CDRL_READER_PASSWORD:?CDRL_READER_PASSWORD is required}"
: "${CDRL_OPERATOR_PASSWORD:?CDRL_OPERATOR_PASSWORD is required}"

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=migrator_password="$CDRL_MIGRATOR_PASSWORD" \
  --set=writer_password="$CDRL_WRITER_PASSWORD" \
  --set=reader_password="$CDRL_READER_PASSWORD" \
  --set=operator_password="$CDRL_OPERATOR_PASSWORD" \
  --file=/docker-entrypoint-initdb.d/002_roles_and_privileges.sql