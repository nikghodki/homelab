#!/bin/sh
# Create or upgrade Temporal's PostgreSQL schemas (idempotent), then idle so the CLI can be exec'd.
set -eu
rm -f /tmp/schema-ready
schema=/etc/temporal/schema/postgresql/v12
for db in temporal temporal_visibility; do
  dir=$schema/temporal/versioned
  [ "$db" = temporal_visibility ] && dir=$schema/visibility/versioned
  # create-database fails if the database exists; --quiet keeps that from being fatal.
  temporal-sql-tool --db "$db" --quiet create-database
  # Version 0.0 only creates the schema_version tables; a no-op once they exist.
  temporal-sql-tool --db "$db" setup-schema -v 0.0
  temporal-sql-tool --db "$db" update-schema -d "$dir"
done
touch /tmp/schema-ready
echo "schemas are current"
trap exit INT HUP TERM
sleep infinity &
wait
