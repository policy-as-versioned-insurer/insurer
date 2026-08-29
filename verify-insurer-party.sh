#!/usr/bin/env bash
# Offline verify for the insurer's party artefact (ticket 21's feed contract,
# ADR-0019; policy-composition ticket 14 for the insurer shape). Gate
# contract (BUILD-BRIEF.md): exit 0 = observed true, exit 3 = could not
# look, else = observed false with FAIL on the last line. No cluster, no
# network -- everything this checks is a file in this repo.
#
# Checks:
#   1. party.yaml parses as YAML.
#   2. roles includes "insurer" and "publisher" (the quote feed is declared; its
#      first version is ticket 36).
#   3. every publishes[] entry's `path` is a directory that exists.
#   4. every publishes[] entry's `payload_schema` file parses as JSON.
#   5. party.yaml validates against platform/party/schema.json through
#      platform/party/party_artefact.py (exit 3 if no sibling platform checkout).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PARTY_FILE="party.yaml"

if [ ! -f "$PARTY_FILE" ]; then
  echo "SKIP: no $PARTY_FILE in $(pwd)"
  exit 3
fi

python3 - "$PARTY_FILE" <<'PYEOF'
import sys, json, os
import yaml

path = sys.argv[1]

try:
    with open(path) as f:
        party = yaml.safe_load(f)
except Exception as e:
    print(f"FAIL: {path} did not parse as YAML: {e}")
    sys.exit(1)

if not isinstance(party, dict):
    print(f"FAIL: {path} did not parse to an object")
    sys.exit(1)

roles = party.get("roles")
if not isinstance(roles, list):
    print(f"FAIL: {path} roles is missing or not a list")
    sys.exit(1)
if "insurer" not in roles:
    print(f"FAIL: {path} roles {roles} missing insurer")
    sys.exit(1)

# publishes[] arrived with the first quotes (ticket 36). Kept conditional: a
# party that publishes nothing must not claim the publisher role either.
publishes = party.get("publishes") or []
if publishes and "publisher" not in roles:
    print(f"FAIL: {path} declares publishes[] without the publisher role")
    sys.exit(1)

for entry in publishes:
    p = entry.get("path")
    if not p or not os.path.isdir(p):
        print(f"FAIL: publishes[] path '{p}' is not a directory")
        sys.exit(1)

    schema_path = entry.get("payload_schema")
    if not schema_path or not os.path.isfile(schema_path):
        print(f"FAIL: publishes[] payload_schema '{schema_path}' does not exist")
        sys.exit(1)
    try:
        with open(schema_path) as f:
            json.load(f)
    except Exception as e:
        print(f"FAIL: payload_schema '{schema_path}' did not parse as JSON: {e}")
        sys.exit(1)

print(f"OK: {path} parses, roles include insurer, "
      f"{len(publishes)} publishes[] entry(ies) each with a real path "
      f"and a valid-JSON payload_schema")
sys.exit(0)
PYEOF
status=$?
[ $status -eq 0 ] || exit 1

checker="${PLATFORM_DIR:-../platform}/party/party_artefact.py"
if [ ! -f "$checker" ]; then
  echo "SKIP: no platform checkout beside this repo (set PLATFORM_DIR) -- cannot validate party.yaml against platform/party/schema.json"
  exit 3
fi
python3 "$checker" check "$PARTY_FILE" || { echo "FAIL: party.yaml does not validate against platform/party/schema.json"; exit 1; }

if [ $status -eq 0 ]; then
  echo "PASS: insurer party artefact"
  exit 0
else
  exit 1
fi
