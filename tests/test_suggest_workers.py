"""Suggest a sensible 'Parallel subjects' value for this machine (not everyone has 32 cores)."""
import re
import unittest

from lib.utils import suggest_stats_workers


class TestSuggestStatsWorkers(unittest.TestCase):
    def test_big_machine_is_capped(self):
        self.assertEqual(suggest_stats_workers(32, 146)["suggested"], 16)

    def test_leaves_headroom_for_the_system(self):
        self.assertEqual(suggest_stats_workers(8, 64)["suggested"], 6)
        self.assertEqual(suggest_stats_workers(4, 64)["suggested"], 3)

    def test_memory_can_be_the_limit(self):
        # ~4 GB per heavy worker
        r = suggest_stats_workers(8, 8)
        self.assertEqual(r["suggested"], 2)
        self.assertEqual(r["max_by_memory"], 2)

    def test_unknown_memory_is_ignored(self):
        self.assertEqual(suggest_stats_workers(8, None)["suggested"], 6)

    def test_tiny_or_unknown_machine_gets_one(self):
        self.assertEqual(suggest_stats_workers(1, 2)["suggested"], 1)
        self.assertEqual(suggest_stats_workers(None, None)["suggested"], 1)
        self.assertEqual(suggest_stats_workers(2, 1)["suggested"], 1)

    def test_reports_inputs(self):
        r = suggest_stats_workers(8, 64)
        self.assertEqual((r["cpus"], r["mem_available_gb"]), (8, 64))
