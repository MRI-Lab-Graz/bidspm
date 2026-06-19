import unittest
from unittest.mock import patch

import bidspm
from lib.core import PipelineResult


class TestBidspmCli(unittest.TestCase):
    def test_stats_workers_defaults_to_four(self):
        with patch("sys.argv", ["bidspm.py"]):
            args = bidspm.parse_arguments()
        self.assertEqual(args.stats_workers, 4)

    def test_stats_workers_accepts_override(self):
        with patch("sys.argv", ["bidspm.py", "--stats-workers", "1"]):
            args = bidspm.parse_arguments()
        self.assertEqual(args.stats_workers, 1)

    def test_main_threads_stats_workers_into_pipeline_options(self):
        captured_options = {}

        fake_result = PipelineResult(
            success=True,
            subjects_processed=["01"],
            subjects_failed=[],
            actions_completed=["stats"],
            log_file="log.txt",
            errors=[],
            warnings=[],
        )

        class _FakePipeline:
            def __init__(self, options):
                captured_options["options"] = options

            def run(self):
                return fake_result

        with patch("sys.argv", [
            "bidspm.py", "--action", "stats", "--stats-workers", "7", "--dry-run",
        ]), patch("bidspm.Pipeline", _FakePipeline):
            with self.assertRaises(SystemExit) as exit_ctx:
                bidspm.main()

        self.assertEqual(exit_ctx.exception.code, 0)
        self.assertEqual(captured_options["options"].stats_workers, 7)


if __name__ == "__main__":
    unittest.main()
