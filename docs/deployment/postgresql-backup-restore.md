# PostgreSQL backup and restore

This runbook covers the application-owned PostgreSQL database used by the monitoring platform. It is intended for internal company-network operations and does not back up Wazuh, Zabbix, Snipe-IT, Freshservice, or Grafana itself.

The database contains sensitive application state, including user password hashes, sessions, audit records, synchronized ticket/asset data, cached Zabbix data, and device-correlation records. Treat every backup as sensitive. Store backups only in an approved protected location inside the company network, use encrypted storage where required by company policy, and do not commit backup files to Git.

## Safety boundary

Creating a backup is read-only against PostgreSQL. Restoring into the production database is destructive and requires a maintenance window plus explicit approval before any live database, service, or data change.

Never place `POSTGRES_PASSWORD`, application secrets, API tokens, or source credentials on a command line or inside a backup filename. The Compose PostgreSQL service already receives its database credentials through the protected environment.

A production restore must not be used as the first test of a backup. Validate the archive format and rehearse restoration on an isolated non-production PostgreSQL instance first.

## Current repository/runtime expectations

At the time this runbook was prepared, the project uses PostgreSQL 16 and the migration history has one Alembic head. Do not hard-code an old migration revision into operations. Verify the active revision each time:

```bash
.venv/bin/alembic heads
docker compose exec -T fastapi-api alembic current
```

Acceptance requires exactly one intended head and the running database to be at that head before a normal release. If the values differ, investigate before taking a release backup or starting a restore.

## Create a protected custom-format backup

Run from the repository root with the correct `.env` already configured. Choose an approved backup directory outside the Git repository:

```bash
export BACKUP_DIR=/path/to/approved/internal-backup-directory
```

Do not use a repository subdirectory for real backups.

Validate the Compose configuration and PostgreSQL health first:

```bash
docker compose config --quiet
docker compose ps postgresql
```

Create the archive with restrictive permissions and an atomic final rename:

```bash
umask 077
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$BACKUP_DIR/monitoring-$STAMP.dump"
PARTIAL="$BACKUP.partial"

rm -f "$PARTIAL"

docker compose exec -T postgresql sh -lc \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=6 --no-owner --no-privileges' \
  > "$PARTIAL"

mv "$PARTIAL" "$BACKUP"
chmod 600 "$BACKUP"
sha256sum "$BACKUP" > "$BACKUP.sha256"
chmod 600 "$BACKUP.sha256"
```

The custom archive supports validation and selective inspection with `pg_restore`. `--no-owner` and `--no-privileges` keep the archive portable between equivalent deployments without importing host-specific ownership or grant metadata.

## Validate every backup immediately

Verify the checksum file and confirm PostgreSQL can read the archive catalog:

```bash
sha256sum -c "$BACKUP.sha256"
docker compose exec -T postgresql pg_restore --list < "$BACKUP" > /dev/null
```

Both commands must succeed. A zero-byte file, checksum failure, or `pg_restore --list` failure means the backup is not acceptable.

Record at least:

- backup UTC timestamp;
- Git commit/release being backed up;
- output of `alembic heads`;
- output of `alembic current`;
- backup filename and SHA-256 checksum;
- PostgreSQL major version;
- operator/reviewer according to company process.

Do not record passwords, tokens, private keys, or source credentials in the acceptance record.

## Non-production restore rehearsal

A restore rehearsal must use an isolated PostgreSQL 16 instance with no published network port and no monitoring-source credentials. Do not rehearse by creating a test database inside the production PostgreSQL cluster.

One safe pattern is a disposable local container with `--network none` and a temporary password file. Run this only on an approved non-production/test host:

```bash
umask 077
RESTORE_CONTAINER=monitoring-restore-check
PASSWORD_FILE=$(mktemp)
openssl rand -hex 32 > "$PASSWORD_FILE"
chmod 600 "$PASSWORD_FILE"

docker run -d --name "$RESTORE_CONTAINER" \
  --network none \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password \
  -e POSTGRES_DB=monitoring_restore \
  -v "$PASSWORD_FILE:/run/secrets/postgres_password:ro" \
  postgres:16-alpine

until docker exec "$RESTORE_CONTAINER" \
  pg_isready -U postgres -d monitoring_restore > /dev/null 2>&1; do
  sleep 1
done

docker exec -i "$RESTORE_CONTAINER" \
  pg_restore -U postgres -d monitoring_restore --no-owner --no-privileges \
  < "$BACKUP"

docker exec "$RESTORE_CONTAINER" \
  psql -U postgres -d monitoring_restore -Atqc \
  'select version_num from alembic_version;'

docker exec "$RESTORE_CONTAINER" \
  psql -U postgres -d monitoring_restore -Atqc \
  "select tablename from pg_tables where schemaname='public' order by tablename;"
```

After collecting the result, remove the isolated test container and temporary password file:

```bash
docker rm -f "$RESTORE_CONTAINER"
rm -f "$PASSWORD_FILE"
unset PASSWORD_FILE RESTORE_CONTAINER
```

The rehearsal passes when the archive restores without errors, the `alembic_version` row exists, and the expected application tables are present. Do not compare or expose sensitive row contents as part of routine restore validation.

## Production restore procedure

Production restoration is intentionally not automated by this repository because it replaces application-owned data. Obtain explicit approval immediately before performing it.

Before the maintenance window:

1. Confirm the selected archive checksum with `sha256sum -c`.
2. Confirm `pg_restore --list` can read the archive.
3. Confirm the archive was successfully rehearsed on an isolated PostgreSQL 16 instance.
4. Identify the Git/image revision associated with the backup.
5. Confirm a rollback/recovery decision owner is available.
6. Take a new pre-restore backup of the current database when the database is still readable.

When approved, stop application components that can read/write application state:

```bash
docker compose stop background-worker fastapi-api
```

Confirm PostgreSQL itself remains healthy. Then recreate only the application database from the validated archive:

```bash
docker compose exec -T postgresql sh -lc \
  'dropdb -U "$POSTGRES_USER" --maintenance-db=postgres --if-exists "$POSTGRES_DB"'

docker compose exec -T postgresql sh -lc \
  'createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'

docker compose exec -T postgresql sh -lc \
  'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges' \
  < "$BACKUP"
```

Before restarting the application, inspect the restored migration revision directly from PostgreSQL:

```bash
docker compose exec -T postgresql sh -lc \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select version_num from alembic_version"'
```

Use the application code/image revision that corresponds to the restored database whenever practical. The FastAPI entrypoint runs `alembic upgrade head` at normal startup, so starting a newer application image may migrate an older restored database. Do not allow that migration implicitly unless the migration path has been reviewed and approved for the recovery.

When the restored database revision and application revision are compatible, start the API first and validate it before starting the worker:

```bash
docker compose up -d fastapi-api
docker compose exec -T fastapi-api alembic heads
docker compose exec -T fastapi-api alembic current
curl --fail --show-error http://127.0.0.1:8000/health

docker compose up -d background-worker
```

If `APP_PORT` differs from `8000`, use the configured loopback port.

After the worker starts, perform the backend acceptance checks in `docs/deployment/backend-acceptance.md`. If any restore or validation step fails, keep the application/worker stopped and investigate instead of repeatedly modifying database state.

## What is not included

This procedure does not define:

- company backup retention, RPO, or RTO policy;
- off-host backup transport or storage product;
- encryption-key custody;
- Grafana database/dashboard backup;
- Wazuh, Zabbix, Snipe-IT, or Freshservice backups;
- automatic production restoration.

Those items must follow the company deployment and continuity requirements. No backup containing monitoring/application data may leave the company network without explicit architecture and security approval.

## Validation status

The repository procedure and PostgreSQL command pattern can be validated without changing production data. A full production restore must remain unperformed until an approved maintenance/recovery exercise. Any real restore result must be recorded separately as runtime evidence.
