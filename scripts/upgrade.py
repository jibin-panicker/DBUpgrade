"""OCI control-plane upgrade; requires Python 3.9+ and OCI CLI 3.94.2.

No database password, SSH access, or third-party Python modules are needed.
Do not run concurrent maintenance through another repository or OCI Console.
"""
import datetime as dt
import json
import os
import subprocess
import time


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def cli(*args):
    result = subprocess.run(
        ['oci', '--auth', 'instance_principal', '--region', os.environ['OCI_CLI_REGION'],
         '--output', 'json', '--no-retry', *args],
        check=True, text=True, stdout=subprocess.PIPE, timeout=180,
    )
    return json.loads(result.stdout)['data']


def get_database(database_id):
    return cli('db', 'database', 'get', '--database-id', database_id)


def history(database_id):
    return cli('db', 'database', 'list-upgrade-history', '--database-id', database_id, '--all') or []


def select_entry(entries, old_ids, action, target):
    new = [e for e in entries if e['id'] not in old_ids]
    require(len(new) <= 1, 'Concurrent upgrade history detected. Inspect OCI; do not retry.')
    if not new:
        return None
    entry = new[0]
    require(entry['action'] == action and entry.get('target-db-version') == target,
            'Unexpected upgrade history. Inspect OCI; do not retry.')
    return entry


def perform(database_id, action, target, timeout=14400):
    previous = history(database_id)
    require(not any(e['lifecycle-state'] == 'IN_PROGRESS' for e in previous),
            'An upgrade operation is already running.')
    old_ids = {e['id'] for e in previous}
    source = json.dumps({'source': 'DB_VERSION', 'dbVersion': target})
    print(f'Submitting {action} for {database_id} to {target}', flush=True)
    # Submit exactly once. A network failure may occur AFTER OCI accepts this request.
    cli('db', 'database', 'upgrade', '--database-id', database_id,
        '--action', action, '--database-upgrade-source-details', source)
    deadline = time.monotonic() + timeout
    observed_id = None
    while time.monotonic() < deadline:
        entry = select_entry(history(database_id), old_ids, action, target)
        if entry:
            require(observed_id in (None, entry['id']), 'Operation identity changed.')
            observed_id = entry['id']
            state = entry['lifecycle-state']
            print(f'{action}: {observed_id} {state}', flush=True)
            require(state in ('IN_PROGRESS', 'SUCCEEDED'),
                    f'{action} failed: {entry.get("lifecycle-details")}')
            if state == 'SUCCEEDED':
                return entry
        time.sleep(30)
    raise RuntimeError('Monitoring timed out. OCI may still be running. Inspect OCI before any rerun.')


def validate_backup(backup, database_id, now):
    require(backup.get('database-id') == database_id, 'Backup belongs to a different database.')
    require(backup.get('lifecycle-state') == 'ACTIVE', 'Backup is not ACTIVE.')
    require(backup.get('type') == 'FULL', 'An on-demand FULL backup is required.')
    end = dt.datetime.fromisoformat((backup.get('time-ended') or '').replace('Z', '+00:00'))
    age = (now - end).total_seconds()
    require(0 <= age <= 86400, 'Backup must have completed within the last 24 hours.')


def inspect(database_id, system_id):
    database = get_database(database_id)
    require(database.get('db-system-id') == system_id, 'Database/DB system mismatch; Base DB only.')
    require(database['lifecycle-state'] == 'AVAILABLE', 'Database is not AVAILABLE.')
    require(database.get('is-cdb') is True, 'Convert non-CDB to CDB/PDB before using this workflow.')
    require(not database.get('data-guard-group'), 'Data Guard requires a topology-specific workflow.')
    associations = cli('db', 'data-guard-association', 'list', '--database-id', database_id, '--all')
    require(not associations, 'Data Guard requires a topology-specific workflow.')
    system = cli('db', 'system', 'get', '--db-system-id', system_id)
    require(system['lifecycle-state'] == 'AVAILABLE', 'DB system is not AVAILABLE.')
    require(system.get('node-count') == 1, 'This workflow supports single-node DB systems only.')
    home = cli('db', 'db-home', 'get', '--db-home-id', database['db-home-id'])
    require(home['db-version'].startswith('19.'), 'Expected a 19c source; do not blindly rerun upgrades.')
    return database, system


def main():
    operation = os.environ['OPERATION']
    require(operation in ('discover', 'precheck', 'upgrade'), 'Invalid operation.')
    for name in ('DATABASE_ID', 'DB_SYSTEM_ID', 'OCI_CLI_REGION'):
        require(bool(os.environ.get(name)), f'Missing {name}.')
    database_id, system_id = os.environ['DATABASE_ID'], os.environ['DB_SYSTEM_ID']
    database, system = inspect(database_id, system_id)
    versions = cli('db', 'version', 'list', '--compartment-id', database['compartment-id'],
                   '--db-system-id', system_id, '--is-upgrade-supported', 'true', '--all') or []
    available = [v['version'] for v in versions]
    print('OCI upgrade candidates: ' + json.dumps(available))
    print('DB system GI version: ' + str(system.get('version')))
    if operation == 'discover':
        return
    target = os.environ.get('TARGET_VERSION', '')
    require(target and target in available, 'Target is not an available OCI upgrade version.')
    require(target == os.environ.get('APPROVED_26AI_VERSION'),
            'Target must match the exact 26ai version approved by your DBA in environment variables.')
    require(os.environ.get('READINESS_CONFIRMED') == 'true',
            'DBA must complete the README readiness checklist and set OCI_26AI_READINESS_CONFIRMED=true.')
    if operation == 'upgrade':
        require(os.environ.get('CONFIRMATION') == f'UPGRADE {database_id}', 'Confirmation does not match.')
        require(bool(os.environ.get('BACKUP_ID')), 'Supply a completed manual FULL backup OCID.')
        backup = cli('db', 'backup', 'get', '--backup-id', os.environ['BACKUP_ID'])
        validate_backup(backup, database_id, dt.datetime.now(dt.timezone.utc))
        require(database.get('db-backup-config', {}).get('auto-backup-enabled') is False,
                'Disable automatic backups for the maintenance window before upgrade.')
    # Every upgrade gets a fresh precheck after the environment approval.
    perform(database_id, 'PRECHECK', target, timeout=3600)
    if operation == 'precheck':
        print('Oracle precheck succeeded. No upgrade submitted.')
        return
    database, _ = inspect(database_id, system_id)
    require(database.get('db-backup-config', {}).get('auto-backup-enabled') is False,
            'Automatic backups were re-enabled; stop and review.')
    validate_backup(cli('db', 'backup', 'get', '--backup-id', os.environ['BACKUP_ID']),
                    database_id, dt.datetime.now(dt.timezone.utc))
    perform(database_id, 'UPGRADE', target)
    database = get_database(database_id)
    home = cli('db', 'db-home', 'get', '--db-home-id', database['db-home-id'])
    require(database['lifecycle-state'] == 'AVAILABLE', 'Final database state is not AVAILABLE.')
    require(home['db-version'] == target, 'Final DB home version differs from requested target.')
    print('OCI upgrade succeeded. Complete SQL/application acceptance and re-enable backups per README.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'FAILED: {exc}', flush=True)
        print('No automatic retry or rollback. Check OCI upgrade history and backup configuration.', flush=True)
        raise SystemExit(1)
