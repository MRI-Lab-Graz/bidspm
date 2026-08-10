import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import bidspm_gui
from lib.project_manager import ProjectManager


class TestRunEndpointBmsModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bidspm_gui.app.config.update(TESTING=True)
        cls.client = bidspm_gui.app.test_client()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        pm = ProjectManager(Path(self.temp_dir.name) / 'projects')
        self._pm_patch = patch.object(bidspm_gui, 'project_manager', pm)
        self._pm_patch.start()
        self.addCleanup(self._pm_patch.stop)
        reg = bidspm_gui.execution_registry
        self._orig = (dict(reg.executions), reg.current_execution_id, reg.current_project_id)
        reg.executions.clear()
        reg.current_execution_id = None
        reg.current_project_id = None
        self.addCleanup(self._restore, reg)

    def _restore(self, reg):
        orig_execs, orig_eid, orig_pid = self._orig
        reg.executions.clear()
        reg.executions.update(orig_execs)
        reg.current_execution_id = orig_eid
        reg.current_project_id = orig_pid

    def test_bms_model_files_added_to_command(self):
        with patch('subprocess.Popen') as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc
            resp = self.client.post('/run', json={
                'actions': ['bms'],
                'bms_model_files': ['/tmp/a.json', '/tmp/b.json'],
            })
        self.assertEqual(resp.status_code, 200)
        # command is the first positional arg to Popen (after ['nohup', ...])
        call_args = mock_popen.call_args[0][0]
        self.assertIn('--models', call_args)
        idx = call_args.index('--models')
        self.assertEqual(call_args[idx + 1], '/tmp/a.json')
        self.assertEqual(call_args[idx + 2], '/tmp/b.json')

    def test_no_models_flag_when_bms_model_files_empty(self):
        with patch('subprocess.Popen') as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc
            resp = self.client.post('/run', json={
                'actions': ['bms'],
                'bms_model_files': [],
            })
        self.assertEqual(resp.status_code, 200)
        call_args = mock_popen.call_args[0][0]
        self.assertNotIn('--models', call_args)


if __name__ == '__main__':
    unittest.main()
