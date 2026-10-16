import json
import tempfile
import unittest
from pathlib import Path

from tests.browser_support import chromium_available, make_dataset, post_json, start_server, sync_playwright
from tests.preflight_support import make_trees, write_model

START = "**/api/preflight/start"
STREAM = "**/api/preflight/stream/**"
CANCEL = "**/api/preflight/cancel/**"
JSON = "application/json"


def ev(phase, state="progress", **kw):
    return {"phase": phase, "state": state, "message": "", "index": None, "total": None, "subject": None,
            "elapsed": 0.1, "items": [], **kw}


def sse(events, first_seq=0):
    return "".join(f"id: {i}\ndata: {json.dumps({**e, 'seq': i})}\n\n" for i, e in enumerate(events, first_seq))


def item(message, severity="error", subject=None):
    return {"id": "x", "severity": severity, "subject": subject, "message": message, "fix": "do something"}


HEAD = [ev("folders", "start"), ev("folders", "done"), ev("validator", "start"), ev("validator", "done"),
        ev("model", "start"), ev("model", "done"), ev("subjects", "start", total=3)]


def subject_step(i, items=()):
    return ev("subjects", index=i, total=3, subject=f"0{i}", items=list(items))


def done(checks=(), verdict="ready"):
    return ev("done", "done", verdict=verdict, report={"verdict": verdict, "checks": list(checks)})


@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class TestReadinessPanelMocked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        make_dataset(Path(cls.tmp.name))
        cls.server, cls.base, cls.project_id = start_server(Path(cls.tmp.name))
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.tmp.cleanup()

    def setUp(self):
        self.pages = []
        self.requests = []

    def tearDown(self):
        for p in self.pages:
            p.close()

    def open_page(self, streams=(), start=None):
        """streams: SSE bodies handed out one per stream request (the last one repeats)."""
        page = self.browser.new_page()
        self.pages.append(page)
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        bodies = list(streams)

        def stream(route):
            self.requests.append(route.request.url)
            body = bodies.pop(0) if len(bodies) > 1 else bodies[0]
            route.fulfill(status=200, body=body, content_type="text/event-stream")

        page.route(START, lambda r: r.fulfill(**(start or {"status": 200, "body": '{"id": "j1"}', "content_type": JSON})))
        page.route(STREAM, stream)
        page.route(CANCEL, lambda r: (self.requests.append(r.request.url), r.fulfill(
            status=200, body='{"status": "cancelling"}', content_type=JSON)))
        page.goto(f"{self.base}/analysis/{self.project_id}", wait_until="load")
        return page

    def panel(self, page):
        return page.inner_text("#preflight-panel")

    def test_phases_tick_in_order_and_subject_bar_counts(self):
        page = self.open_page([sse(HEAD + [subject_step(1), subject_step(2), done()])])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .preflight-verdict")
        states = page.eval_on_selector_all("#preflight-panel [data-phase]", "els => els.map(e => [e.dataset.phase, e.dataset.state])")
        self.assertEqual(states, [["folders", "done"], ["validator", "done"], ["model", "done"], ["subjects", "done"]])
        self.assertEqual(self.errors, [])

    def test_subject_bar_shows_i_of_n_mid_run(self):
        page = self.open_page([sse(HEAD + [subject_step(1), subject_step(2)])])  # cut before the terminal event
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertIn("2 / 3 subjects", self.panel(page))
        state = page.eval_on_selector("#preflight-panel [data-phase=subjects]", "e => e.dataset.state")
        self.assertEqual(state, "running")

    def test_validator_phase_is_running_with_indeterminate_bar(self):
        page = self.open_page([sse(HEAD[:3])])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertEqual(page.eval_on_selector("#preflight-panel [data-phase=validator]", "e => e.dataset.state"), "running")
        self.assertEqual(page.locator("#preflight-panel .progress-bar-animated").count(), 1)

    def test_items_appear_live_with_running_counts_before_the_verdict(self):
        steps = [subject_step(1, [item("sub-01 broke")]), subject_step(2, [item("careful", "warning", "02")])]
        page = self.open_page([sse(HEAD + steps)])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        text = self.panel(page)
        self.assertIn("sub-01 broke", text)
        self.assertIn("1 error", text)
        self.assertIn("1 warning", text)
        self.assertEqual(page.locator("#preflight-panel .preflight-verdict").count(), 0)

    def test_final_verdict_keeps_phases_counter_and_checks(self):
        checks = [item("sub-01 broke")]
        page = self.open_page([sse(HEAD + [subject_step(1, checks), subject_step(2), subject_step(3), done(checks, "blocked")])])
        calls = []
        page.expose_function("seen", lambda v: calls.append(v))
        page.evaluate("""() => { const t = document.getElementById('preflight-panel');
            ReadinessPanel.run({target: t, body: {}, onDone: r => seen(r.verdict)}); }""")
        page.wait_for_selector("#preflight-panel .preflight-verdict")
        text = self.panel(page)
        self.assertIn("blocked", text)
        self.assertIn("3 / 3 subjects", text)
        self.assertIn("sub-01 broke", text)
        self.assertEqual(page.locator("#preflight-panel .rp-cancel").count(), 0)
        page.wait_for_function("true")
        self.assertEqual(calls, ["blocked"])

    def test_cancel_posts_to_the_job_and_shows_cancelled(self):
        page = self.open_page([sse(HEAD + [subject_step(1)])])
        page.route(STREAM, lambda r: None)  # never answered: the run stays in progress
        page.click("#btn-preflight")
        page.click("#preflight-panel .rp-cancel")
        page.wait_for_function("document.getElementById('preflight-panel').innerText.includes('Cancelled')")
        self.assertTrue(any(u.endswith("/api/preflight/cancel/j1") for u in self.requests))
        self.assertEqual(page.locator("#preflight-panel .rp-cancel").count(), 0)

    def test_stream_cut_before_terminal_shows_lost_connection_and_retry_resumes(self):
        first = sse(HEAD + [subject_step(1, [item("sub-01 broke")])])  # seq 0..7
        rest = sse([subject_step(2), subject_step(3), done([item("sub-01 broke")], "blocked")], first_seq=8)
        page = self.open_page([first, rest])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-retry")
        self.assertIn("Lost connection to the server", self.panel(page))
        page.click("#preflight-panel .rp-retry")
        page.wait_for_selector("#preflight-panel .preflight-verdict")
        self.assertTrue(self.requests[-1].endswith("from=8"), self.requests)
        self.assertIn("3 / 3 subjects", self.panel(page))
        self.assertEqual(page.locator("#preflight-panel .rp-lost").count(), 0)

    def test_retry_on_vanished_job_shows_its_message(self):
        gone = 'data: {"phase": "error", "message": "job not found"}\n\n'
        page = self.open_page([sse(HEAD), gone])
        page.click("#btn-preflight")
        page.click("#preflight-panel .rp-retry")
        page.wait_for_function("document.getElementById('preflight-panel').innerText.includes('job not found')")
        self.assertEqual(page.locator("#preflight-panel .rp-retry").count(), 0)

    def test_terminal_error_event_shows_its_message(self):
        page = self.open_page([sse(HEAD + [ev("error", "done", message="RuntimeError: boom")])])
        page.click("#btn-preflight")
        page.wait_for_function("document.getElementById('preflight-panel').innerText.includes('RuntimeError: boom')")
        self.assertEqual(page.locator("#preflight-panel .rp-lost").count(), 0)

    def test_non_json_500_on_start_shows_a_message(self):
        page = self.open_page([sse([])], start={"status": 500, "body": "<html>boom</html>", "content_type": "text/html"})
        page.click("#btn-preflight")
        page.wait_for_function("document.getElementById('preflight-panel').innerText.includes('500')")
        self.assertIn("Readiness check failed", self.panel(page))
        self.assertEqual(self.errors, [])

    def test_429_shows_the_servers_text(self):
        msg = "too many readiness checks are running; wait for one to finish or cancel it"
        page = self.open_page([sse([])], start={"status": 429, "body": json.dumps({"error": msg}), "content_type": JSON})
        page.click("#btn-preflight")
        page.wait_for_function("t => document.getElementById('preflight-panel').innerText.includes(t)", arg=msg)
        self.assertEqual(self.requests, [])  # no stream was opened

    def test_event_messages_render_as_text_not_html(self):
        steps = [subject_step(1, [item("/data/<b>x</b> <img src=x onerror=window.pwned=1>")])]
        page = self.open_page([sse(HEAD + steps)])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertEqual(page.locator("#preflight-panel b, #preflight-panel img").count(), 0)
        self.assertIn("<b>x</b>", self.panel(page))
        self.assertIsNone(page.evaluate("window.pwned"))

    def test_late_events_of_an_older_run_are_ignored(self):
        page = self.open_page([sse([])])
        page.evaluate("""() => {
            window.sources = [];
            window.EventSource = class { constructor(url) { this.url = url; this.closed = false; window.sources.push(this); }
                close() { this.closed = true; } };
        }""")
        for _ in range(2):
            page.click("#btn-preflight")
            page.wait_for_function(f"window.sources.length === {_ + 1}")
        page.evaluate("""() => window.sources[0].onmessage({data: JSON.stringify(
            {phase: 'subjects', state: 'progress', index: 2, total: 9, subject: '02', seq: 0,
             items: [{severity: 'error', message: 'STALE', subject: null}]})})""")
        page.evaluate("""() => window.sources[1].onmessage({data: JSON.stringify(
            {phase: 'subjects', state: 'progress', index: 1, total: 3, subject: '01', seq: 0, items: []})})""")
        page.evaluate("""() => window.sources[0].onmessage({data: JSON.stringify(
            {phase: 'error', state: 'done', message: 'STALE failure'})})""")
        text = self.panel(page)
        self.assertIn("1 / 3 subjects", text)  # the older run's late terminal event did not replace the panel
        self.assertNotIn("STALE", text)
        self.assertTrue(page.evaluate("window.sources[0].closed"))

    def test_new_run_closes_the_previous_stream_and_cancels_its_job(self):
        page = self.open_page([sse([])])
        page.evaluate("""() => { window.sources = [];
            window.EventSource = class { constructor(u) { window.sources.push(this); this.closed = false; } close() { this.closed = true; } }; }""")
        page.click("#btn-preflight")
        page.wait_for_function("window.sources.length === 1")
        page.click("#btn-preflight")
        page.wait_for_function("window.sources.length === 2")
        self.assertTrue(page.evaluate("window.sources[0].closed"))
        self.assertTrue(any("/cancel/j1" in u for u in self.requests))


@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class TestReadinessPanelRealServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.subjects = ("01", "02", "03", "04", "05")
        bids, fmriprep = make_trees(root / "data", subjects=cls.subjects)
        model = write_model(root / "data")
        cls.server, cls.base, _ = start_server(root)
        cls.project_id = post_json(cls.base + "/api/projects", {"name": "real", "config": {
            "bids_folder": str(bids), "fmriprep_folder": str(fmriprep), "models_file": str(model),
            "tasks": ["x"], "space": "MNI"}})["project"]["id"]
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.tmp.cleanup()

    def test_check_readiness_streams_to_a_final_verdict(self):
        page = self.browser.new_page()
        try:
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{self.base}/analysis/{self.project_id}", wait_until="load")
            page.select_option("#validator-mode", "skip")
            page.click("#btn-preflight")
            page.wait_for_selector("#preflight-panel .preflight-verdict", timeout=60000)
            text = page.inner_text("#preflight-panel")
            self.assertIn("5 / 5 subjects", text)
            states = page.eval_on_selector_all("#preflight-panel [data-phase]", "els => els.map(e => e.dataset.state)")
            self.assertTrue(states and set(states) == {"done"}, states)
            self.assertNotIn("blocked", text.lower())
            self.assertEqual(errors, [])
        finally:
            page.close()
