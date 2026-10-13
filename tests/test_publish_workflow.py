"""Publishing an image is a decision, not a side effect of tagging: the workflow runs only when dispatched by hand."""
import re
import unittest
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "docker-publish.yml").read_text()


class TestPublishWorkflow(unittest.TestCase):
    def test_only_manual_trigger(self):
        on_block = re.search(r"^on:\n(.*?)(?=^\S)", WORKFLOW, re.S | re.M).group(1)
        self.assertIn("workflow_dispatch", on_block)
        for trigger in ("push:", "pull_request:", "schedule:", "tags:"):
            self.assertNotIn(trigger, on_block)
