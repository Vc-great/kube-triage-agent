#!/usr/bin/env bash
# Runs only on a fresh PostgreSQL volume. No passwords in command arguments/logs.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv dev_user POSTGRES_DEV_USER
\getenv dev_db POSTGRES_DEV_DB
\getenv dev_password POSTGRES_DEV_PASSWORD
CREATE ROLE :"dev_user" LOGIN PASSWORD :'dev_password';
CREATE DATABASE :"dev_db" OWNER :"dev_user";
-- The dev role must not connect to the formal database.
REVOKE CONNECT ON DATABASE :"DBNAME" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"DBNAME" TO CURRENT_USER;
REVOKE CONNECT ON DATABASE :"dev_db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"dev_db" TO :"dev_user";
SQL
