#!/usr/bin/env bash
# Read-only host inspection. Major upgrades remain on the OCI API path.
set -euo pipefail
: "${DBCLI_HOST:?Set environment variable OCI_DBCLI_HOST}"
: "${DBCLI_SSH_KEY:?Set environment secret OCI_DBCLI_SSH_PRIVATE_KEY}"
: "${DBCLI_KNOWN_HOSTS:?Set environment secret OCI_DBCLI_KNOWN_HOSTS}"
# Accept a DNS name or IPv4 address, never SSH options or shell metacharacters.
[[ "$DBCLI_HOST" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || {
  echo "OCI_DBCLI_HOST must be a DNS name or IPv4 address" >&2
  exit 1
}
umask 077
inspection_dir=$(mktemp -d "${RUNNER_TEMP:-/tmp}/dbcli-inspect.XXXXXXXX")
trap 'rm -rf "$inspection_dir"' EXIT
printf '%s\n' "$DBCLI_SSH_KEY" > "$inspection_dir/key"
printf '%s\n' "$DBCLI_KNOWN_HOSTS" > "$inspection_dir/known_hosts"
unset DBCLI_SSH_KEY DBCLI_KNOWN_HOSTS
ssh -F /dev/null -T \
  -i "$inspection_dir/key" \
  -o BatchMode=yes -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile="$inspection_dir/known_hosts" \
  -o ConnectTimeout=20 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  "opc@$DBCLI_HOST" 'bash -se' <<'REMOTE'
set -euo pipefail
sudo -n /opt/oracle/dcs/bin/dbcli list-databases
sudo -n /opt/oracle/dcs/bin/dbcli list-dbhomes
sudo -n /opt/oracle/dcs/bin/dbcli list-jobs
REMOTE
