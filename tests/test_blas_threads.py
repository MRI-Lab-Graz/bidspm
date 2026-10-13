"""Parallel stats workers must not each start a full set of BLAS/OpenMP threads.

Measured on 32 cores, 3 parallel 132 subjects: unrestricted 394 s, 1 thread each 115 s,
10 threads each 110 s (model specification alone: 200 s vs 16 s).
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lib.core as core
from lib.config import ContainerConfig
from lib.core import Pipeline, PipelineOptions
from tests.test_core_helpers import _make_config

KEYS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")


class TestBlasThreadEnv(unittest.TestCase):
    def test_threads_split_across_workers(self):
        self.assertEqual(core._blas_thread_env(workers=4, cpus=32), dict.fromkeys(KEYS, "8"))
        self.assertEqual(core._blas_thread_env(workers=8, cpus=32), dict.fromkeys(KEYS, "4"))

    def test_capped_for_few_workers(self):
        self.assertEqual(core._blas_thread_env(workers=1, cpus=32), dict.fromkeys(KEYS, "8"))
        self.assertEqual(core._blas_thread_env(workers=3, cpus=32), dict.fromkeys(KEYS, "8"))

    def test_never_below_one(self):
        self.assertEqual(core._blas_thread_env(workers=64, cpus=32), dict.fromkeys(KEYS, "1"))
        self.assertEqual(core._blas_thread_env(workers=4, cpus=None), dict.fromkeys(KEYS, "1"))


class TestPipelinePassesThreads(unittest.TestCase):
    def test_container_env_uses_active_worker_count(self):
        pipeline = Pipeline(PipelineOptions(actions=["stats"], stats_workers=4))
        pipeline._workers = 16
        with patch("lib.core.os.cpu_count", return_value=32):
            env = pipeline._container_env()
        for k in KEYS:
            self.assertEqual(env[k], "2")

    def test_threads_reach_the_container_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = Pipeline(PipelineOptions(actions=["stats"], dry_run=True))
            pipeline.config = _make_config(Path(tmp))
            pipeline.container_config = ContainerConfig(container_type="docker", docker_image="x:latest")
            pipeline.model_file_path = None
            with patch("lib.core.build_container_command", return_value=(["docker"], None)) as build:
                pipeline._run_container_action("stats", "01", "motor")
        self.assertIn("OPENBLAS_NUM_THREADS", build.call_args.kwargs["extra_env"])
