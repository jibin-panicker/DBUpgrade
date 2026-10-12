import datetime as dt
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('upgrade', Path(__file__).parents[1] / 'scripts/upgrade.py')
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


class UpgradeTests(unittest.TestCase):
    def entry(self, identifier='new', state='SUCCEEDED', target='target'):
        return {'id': identifier, 'action': 'PRECHECK', 'target-db-version': target,
                'lifecycle-state': state}

    def test_old_success_does_not_count(self):
        self.assertIsNone(upgrade.select_entry([self.entry('old')], {'old'}, 'PRECHECK', 'target'))

    def test_wrong_target_fails(self):
        with self.assertRaises(RuntimeError):
            upgrade.select_entry([self.entry(target='wrong')], set(), 'PRECHECK', 'target')

    def test_concurrent_history_fails(self):
        with self.assertRaises(RuntimeError):
            upgrade.select_entry([self.entry('a'), self.entry('b')], set(), 'PRECHECK', 'target')

    def test_waits_for_new_success_and_submits_once(self):
        with patch.object(upgrade, 'history', side_effect=[[], [], [self.entry(state='IN_PROGRESS')], [self.entry()]]), \
             patch.object(upgrade, 'cli') as cli, patch.object(upgrade.time, 'sleep'):
            self.assertEqual(upgrade.perform('db', 'PRECHECK', 'target')['id'], 'new')
            self.assertEqual(cli.call_count, 1)

    def test_failed_precheck_stops(self):
        with patch.object(upgrade, 'history', side_effect=[[], [self.entry(state='FAILED')]]), \
             patch.object(upgrade, 'cli'):
            with self.assertRaises(RuntimeError):
                upgrade.perform('db', 'PRECHECK', 'target')

    def test_inflight_operation_blocks_submission(self):
        with patch.object(upgrade, 'history', return_value=[self.entry(state='IN_PROGRESS')]), \
             patch.object(upgrade, 'cli') as cli:
            with self.assertRaises(RuntimeError):
                upgrade.perform('db', 'PRECHECK', 'target')
            cli.assert_not_called()

    def test_timeout_is_failure(self):
        with patch.object(upgrade, 'history', return_value=[]), patch.object(upgrade, 'cli'):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                upgrade.perform('db', 'PRECHECK', 'target', timeout=0)

    def test_rejects_rac_before_upgrade(self):
        db = {'db-system-id': 'system', 'lifecycle-state': 'AVAILABLE', 'is-cdb': True}
        system = {'lifecycle-state': 'AVAILABLE', 'node-count': 2}
        with patch.object(upgrade, 'get_database', return_value=db), \
             patch.object(upgrade, 'cli', side_effect=[[], system]):
            with self.assertRaisesRegex(RuntimeError, 'single-node'):
                upgrade.inspect('db', 'system')

    def test_rejects_data_guard(self):
        db = {'db-system-id': 'system', 'lifecycle-state': 'AVAILABLE', 'is-cdb': True}
        with patch.object(upgrade, 'get_database', return_value=db), \
             patch.object(upgrade, 'cli', return_value=[{'id': 'association'}]):
            with self.assertRaisesRegex(RuntimeError, 'Data Guard'):
                upgrade.inspect('db', 'system')

    def test_backup_guards(self):
        now = dt.datetime.now(dt.timezone.utc)
        valid = {'database-id': 'db', 'lifecycle-state': 'ACTIVE', 'type': 'FULL',
                 'time-ended': (now - dt.timedelta(hours=1)).isoformat()}
        upgrade.validate_backup(valid, 'db', now)
        for replacement in ({'database-id': 'other'}, {'lifecycle-state': 'CREATING'},
                            {'type': 'INCREMENTAL'},
                            {'time-ended': (now - dt.timedelta(hours=25)).isoformat()},
                            {'time-ended': (now + dt.timedelta(hours=1)).isoformat()}):
            with self.subTest(replacement=replacement), self.assertRaises(RuntimeError):
                upgrade.validate_backup(dict(valid, **replacement), 'db', now)


if __name__ == '__main__':
    unittest.main()
