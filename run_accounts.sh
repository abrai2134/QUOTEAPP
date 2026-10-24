#!/usr/bin/env bash
# Start the Accounts Desk.  The first run asks you to create the admin login.
set -euo pipefail
cd "$(dirname "$0")"
if [ -f .env ]; then set -a; . ./.env; set +a; fi
if [ ! -d .venv ]; then
  echo "Creating virtual environment…"
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
fi
.venv/bin/pip install --quiet -r requirements.txt
echo
echo "  Accounts Desk running at  http://localhost:${ACCOUNTS_PORT:-5100}"
echo "  (the team opens the same address using this machine's IP)"
echo
exec .venv/bin/python -m accounts.main
