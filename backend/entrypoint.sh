#!/bin/sh
set -e
python -m alembic check
exec "$@"
