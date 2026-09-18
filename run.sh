#!/usr/bin/env bash
# Start the quotation app.  First run creates the database and imports the CSVs.
set -euo pipefail
cd "$(dirname "$0")"

# Optional e-mail settings live in .env (never committed).
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

if [ ! -d .venv ]; then
  echo "Creating virtual environment…"
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

.venv/bin/python -m app.seed
echo
echo "  Quotation app running at  http://localhost:${PORT:-5000}"
echo "  (open the same address from your phone using this machine's IP)"
echo
exec .venv/bin/python -m app.main
