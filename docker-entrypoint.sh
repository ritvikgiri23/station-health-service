#!/bin/sh
# Apply database migrations, then hand over to the container command.
set -e

flask --app station_health.app:create_app db upgrade

exec "$@"
