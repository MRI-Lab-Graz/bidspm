import json
import tempfile
import unittest
from pathlib import Path

from tests.browser_support import (chromium_available, make_dataset, post_json, start_server, sync_playwright, go_to_stage)
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


class _Pacer:
    """Tiny local SSE server: sends one group of events per released gate, so tests control pacing."""

    def __init__(self, groups):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.gates = [threading.Event() for _ in groups]
        self.gates[0].set()
        gates = self.gates

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                for gate, body in zip(gates, groups):
                    if not gate.wait(30):
                        return
                    self.wfile.write(body.encode())
                    self.wfile.flush()

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/stream"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        for g in self.gates:
            g.set()
        self.httpd.shutdown()
        self.httpd.server_close()


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
        go_to_stage(page, "run")
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
        self.assertIn("2 / 3 subject checks", self.panel(page))
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
        self.assertIn("3 / 3 subject checks", text)
        self.assertIn("sub-01 broke", text)
        self.assertEqual(page.locator("#preflight-panel .rp-cancel").count(), 0)
        self.assertEqual(calls, ["blocked"])  # onDone ran before the verdict became visible to the test

    def test_cancel_posts_to_the_job_and_shows_cancelled(self):
        page = self.open_page([sse(HEAD + [subject_step(1)])])
        page.route(STREAM, lambda r: None)  # never answered: the run stays in progress
        page.click("#btn-preflight")
        page.click("#preflight-panel .rp-cancel")
        page.wait_for_function("document.getElementById('preflight-panel').innerText.includes('Cancelled')")
        self.assertTrue(any(u.endswith("/api/preflight/cancel/j1") for u in self.requests))
        self.assertEqual(page.locator("#preflight-panel .rp-cancel").count(), 0)

    def test_bar_turns_indeterminate_after_the_subjects_while_the_validator_still_runs(self):
        head = [e for e in HEAD if not (e["phase"] == "validator" and e["state"] == "done")]  # validator never finishes
        steps = [subject_step(1), subject_step(2), subject_step(3)]
        page = self.open_page([sse(head + steps + [ev("subjects", "done")])])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertEqual(page.locator("#preflight-panel .progress-bar-animated").count(), 1)
        self.assertIsNone(page.get_attribute("#preflight-panel .rp-bar", "aria-valuenow"))
        self.assertIn("3 / 3 subject checks", self.panel(page))

    def test_bar_stays_full_after_the_subjects_when_the_validator_is_done(self):
        steps = [subject_step(1), subject_step(2), subject_step(3)]
        page = self.open_page([sse(HEAD + steps + [ev("subjects", "done")])])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertEqual(page.locator("#preflight-panel .progress-bar-animated").count(), 0)
        self.assertEqual(page.get_attribute("#preflight-panel .rp-bar", "aria-valuenow"), "100")

    def test_pagehide_cancels_a_live_job_but_not_a_finished_one(self):
        page = self.open_page([sse(HEAD + [subject_step(1)])])
        page.route(STREAM, lambda r: None)  # never answered: the run stays live
        with page.expect_request(lambda r: "/api/preflight/stream/" in r.url):  # the job id is known once streaming starts
            page.click("#btn-preflight")
        with page.expect_request(lambda r: r.url.endswith("/api/preflight/cancel/j1")):
            page.evaluate("window.dispatchEvent(new Event('pagehide'))")
        done_page = self.open_page([sse(HEAD + [subject_step(1), done()])])
        before = len(self.requests)
        done_page.click("#btn-preflight")
        done_page.wait_for_selector("#preflight-panel .preflight-verdict")
        with self.assertRaises(Exception):  # no cancel request may follow for a finished job
            with done_page.expect_request(lambda r: "/cancel/" in r.url, timeout=1000):
                done_page.evaluate("window.dispatchEvent(new Event('pagehide'))")
        self.assertFalse(any("/cancel/" in u for u in self.requests[before:]), self.requests)

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
        self.assertIn("3 / 3 subject checks", self.panel(page))
        self.assertEqual(page.locator("#preflight-panel .rp-lost").count(), 0)

    def test_retry_on_vanished_job_shows_its_message(self):
        gone = 'data: {"phase": "error", "message": "job not found"}\n\n'
        page = self.open_page([sse(HEAD), gone])
        page.click("#btn-preflight")
        page.click("#preflight-panel .rp-retry")
        page.wait_for_function("document.getElementById('preflight-panel').innerText.includes('job not found')")
        page.evaluate("1")  # a round trip: a stray cancel request would have been issued by now
        self.assertFalse(any("/cancel/" in u for u in self.requests), self.requests)
        self.assertEqual(page.locator("#preflight-panel .rp-retry").count(), 0)

    def test_terminal_error_event_shows_its_message(self):
        page = self.open_page([sse(HEAD + [ev("error", "done", message="RuntimeError: boom")])])
        page.click("#btn-preflight")
        page.wait_for_function("document.getElementById('preflight-panel').innerText.includes('RuntimeError: boom')")
        self.assertEqual(page.locator("#preflight-panel .rp-lost").count(), 0)
        self.assertTrue(any(u.endswith("/cancel/j1") for u in self.requests), self.requests)  # frees the server slot

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
        for n in (1, 2):
            page.click("#btn-preflight")
            page.wait_for_function(f"window.sources.length === {n}")
        page.evaluate("""() => window.sources[0].onmessage({data: JSON.stringify(
            {phase: 'subjects', state: 'progress', index: 2, total: 9, subject: '02', seq: 0,
             items: [{severity: 'error', message: 'STALE', subject: null}]})})""")
        page.evaluate("""() => window.sources[1].onmessage({data: JSON.stringify(
            {phase: 'subjects', state: 'progress', index: 1, total: 3, subject: '01', seq: 0, items: []})})""")
        page.evaluate("""() => window.sources[0].onmessage({data: JSON.stringify(
            {phase: 'error', state: 'done', message: 'STALE failure'})})""")
        text = self.panel(page)
        self.assertIn("1 / 3 subject checks", text)  # the older run's late terminal event did not replace the panel
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


    # --- review fixes -------------------------------------------------------------------------------------------

    FAKES = """() => {
        window.sources = []; window.cancels = []; window.starts = []; const realFetch = window.fetch;
        window.EventSource = class { constructor(url) { this.url = url; this.closed = false; window.sources.push(this); }
            close() { this.closed = true; } };
        window.fetch = function (url) {
            if (String(url).endsWith('/start')) {
                return new Promise((resolve) => { window.starts.push(() => resolve(
                    new Response(JSON.stringify({id: 'j' + window.starts.length}), {status: 200}))); });
            }
            if (!String(url).includes('/api/preflight/cancel/')) return realFetch.apply(window, arguments);
            window.cancels.push(String(url));
            return Promise.resolve(new Response('{"status":"cancelling"}', {status: window.cancelStatus || 200}));
        };
    }"""
    SEND = "(args) => window.sources[args[0]].onmessage({data: JSON.stringify(args[1])})"

    def fake_page(self):
        page = self.open_page([sse([])])
        page.evaluate(self.FAKES)
        return page

    def test_a11y_live_region_progressbar_and_glyphs(self):
        page = self.open_page([sse(HEAD + [subject_step(1)])])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertEqual(page.get_attribute("#preflight-panel", "aria-live"), "polite")
        self.assertEqual(page.get_attribute("#preflight-panel", "role"), "status")
        bar = page.locator("#preflight-panel .progress")
        self.assertEqual(bar.get_attribute("role"), "progressbar")
        self.assertEqual([bar.get_attribute(a) for a in ("aria-valuemin", "aria-valuemax", "aria-valuenow")], ["0", "100", "33"])
        self.assertTrue(bar.get_attribute("aria-label"))
        self.assertEqual(page.locator("#preflight-panel .rp-glyph[aria-hidden=true]").count(), 4)
        self.assertIn("(done)", page.text_content("#preflight-panel [data-phase=folders]"))
        self.assertIn("(running)", page.text_content("#preflight-panel [data-phase=subjects]"))

    def test_live_region_is_not_atomic_and_progress_stays_silent(self):
        page = self.open_page([sse(HEAD), sse([done()], first_seq=7)])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertEqual(page.get_attribute("#preflight-panel", "aria-atomic"), "false")
        self.assertEqual(page.get_attribute("#preflight-panel .rp-progress", "aria-live"), "off")
        page.click("#preflight-panel .rp-retry")
        page.wait_for_selector("#preflight-panel[aria-live=polite][aria-atomic=false] .preflight-verdict")

    def test_verdict_and_notices_land_inside_the_live_region(self):
        page = self.open_page([sse(HEAD), sse([done()], first_seq=7)])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertEqual(page.locator("#preflight-panel[aria-live=polite] .rp-lost").count(), 1)
        page.click("#preflight-panel .rp-retry")
        page.wait_for_selector("#preflight-panel[aria-live=polite] .preflight-verdict")

    def test_progress_bar_value_is_clamped(self):
        page = self.open_page([sse(HEAD + [subject_step(9)])])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertEqual(page.get_attribute("#preflight-panel .progress", "aria-valuenow"), "100")

    def test_counter_counts_subject_checks_with_explanation(self):
        steps = [ev("subjects", "start", total=4), ev("subjects", index=3, total=4, subject="02")]
        page = self.open_page([sse(HEAD[:6] + steps)])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertEqual(page.inner_text("#preflight-panel .rp-count"), "3 / 4 subject checks")
        self.assertIn("tasks", page.get_attribute("#preflight-panel .rp-count", "title"))

    def test_stream_lifetime_event_is_a_lost_connection_not_a_verdict(self):
        timeout = 'data: {"phase": "error", "state": "done", "message": "stream timed out"}\n\n'
        page = self.open_page([sse(HEAD) + timeout])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-retry")
        self.assertEqual(page.locator("#preflight-panel .preflight-verdict").count(), 0)
        self.assertFalse(any("/cancel/" in u for u in self.requests))  # the job may still be running

    def test_overlapping_replay_is_deduplicated_by_seq(self):
        first = sse(HEAD + [subject_step(1, [item("dup")])])  # seq 0..7
        replay = sse([subject_step(1, [item("dup")])], first_seq=7)
        page = self.open_page([first, replay])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-retry")
        page.click("#preflight-panel .rp-retry")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertIn("1 error,", self.panel(page))
        self.assertEqual(page.locator("#preflight-panel .rp-items li").count(), 1)

    def test_live_items_are_capped_but_counts_and_final_report_are_complete(self):
        many = [item(f"bad {i}") for i in range(500)]
        first = sse(HEAD + [subject_step(1, many)])
        rest = sse([done(many, "blocked")], first_seq=8)
        page = self.open_page([first, rest])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertLessEqual(page.locator("#preflight-panel .rp-items li").count(), 201)
        text = self.panel(page)
        self.assertIn("500 errors", text)
        self.assertIn("+300 more (see the final report)", text)
        self.assertIn("overflow-y: auto", page.get_attribute("#preflight-panel .rp-items", "style"))
        page.click("#preflight-panel .rp-retry")
        page.wait_for_selector("#preflight-panel .preflight-verdict")
        self.assertEqual(page.locator("#preflight-panel ul li.text-danger").count(), 500)

    def test_cancel_clears_the_lost_notice(self):
        page = self.open_page([sse(HEAD)])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        page.click("#preflight-panel .rp-cancel")
        page.wait_for_function("document.getElementById('preflight-panel').innerText.includes('Cancelled')")
        self.assertEqual(page.locator("#preflight-panel .rp-retry").count(), 0)

    def test_failed_cancel_is_reported_not_silent(self):
        page = self.open_page([sse(HEAD)])
        page.route(CANCEL, lambda r: r.fulfill(status=500, body="boom", content_type="text/plain"))
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        page.click("#preflight-panel .rp-cancel")
        page.wait_for_function("document.getElementById('preflight-panel').innerText.includes('Could not cancel the check on the server')")

    def test_subjects_done_without_index_keeps_the_bar(self):
        page = self.open_page([sse(HEAD + [subject_step(2), ev("subjects", "done")])])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertGreater(int(page.get_attribute("#preflight-panel .progress", "aria-valuenow")), 0)

    def test_unknown_phase_names_are_ignored(self):
        page = self.open_page([sse(HEAD + [ev("constructor", "start"), ev("toString", "done"), subject_step(1)])])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-lost")
        self.assertIn("1 / 3 subject checks", self.panel(page))
        self.assertEqual(self.errors, [])

    def test_total_zero_has_no_nan_and_finishes(self):
        page = self.open_page([sse(HEAD[:6] + [ev("subjects", "start", total=0), done()])])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .preflight-verdict")
        self.assertNotIn("NaN", self.panel(page))

    def test_a_throwing_onDone_does_not_break_the_panel(self):
        page = self.open_page([sse(HEAD + [done()])])
        page.evaluate("""() => ReadinessPanel.run({target: document.getElementById('preflight-panel'), body: {},
            onDone: () => { throw new Error('caller bug'); }})""")
        page.wait_for_selector("#preflight-panel .preflight-verdict")
        self.assertEqual(self.errors, [])

    def test_stream_is_closed_when_the_target_leaves_the_document(self):
        page = self.fake_page()
        page.evaluate("""() => { const t = document.createElement('div'); document.body.append(t); window.t = t;
            ReadinessPanel.run({target: t, body: {}}); window.starts[0](); }""")
        page.wait_for_function("window.sources.length === 1")
        page.evaluate("() => window.t.remove()")
        page.evaluate(self.SEND, [0, {"phase": "folders", "state": "start", "seq": 0}])
        self.assertTrue(page.evaluate("window.sources[0].closed"))
        self.assertTrue(page.evaluate("window.cancels[0]").endswith("/cancel/j1"))  # frees the server slot

    def test_a_target_attached_after_run_is_not_treated_as_detached(self):
        page = self.fake_page()
        page.evaluate("""() => { window.t = document.createElement('div');
            ReadinessPanel.run({target: window.t, body: {}}); window.starts[0](); }""")
        page.wait_for_function("window.sources.length === 1")
        page.evaluate(self.SEND, [0, {"phase": "folders", "state": "start", "seq": 0}])  # not attached yet
        page.evaluate("document.body.append(window.t)")
        page.evaluate(self.SEND, [0, {"phase": "folders", "state": "done", "seq": 1}])
        self.assertFalse(page.evaluate("window.sources[0].closed"))
        self.assertEqual(page.evaluate("window.cancels.length"), 0)

    ANNOUNCED = """() => { const out = [];
        const walk = (n) => { if (n.nodeType === 3) out.push(n.textContent);
            else if (n.getAttribute && n.getAttribute('aria-live') !== 'off') n.childNodes.forEach(walk); };
        walk(document.getElementById('preflight-panel')); return out.join('|'); }"""

    def test_progress_events_are_not_announced_only_the_verdict(self):
        page = self.fake_page()
        page.click("#btn-preflight")
        page.evaluate("window.starts[0]()")
        page.wait_for_function("window.sources.length === 1")
        before = page.evaluate(self.ANNOUNCED)
        for i, e in enumerate(HEAD + [subject_step(1, [item("bad")]), subject_step(2)]):
            page.evaluate(self.SEND, [0, {**e, "seq": i}])
        self.assertIn("2 / 3 subject checks", self.panel(page))
        self.assertEqual(page.evaluate(self.ANNOUNCED), before)
        page.evaluate(self.SEND, [0, {**done([item("bad")], "blocked"), "seq": 99}])
        self.assertIn("blocked", page.evaluate(self.ANNOUNCED))

    def test_failure_and_lost_connection_are_announced_once_by_the_status_region(self):
        page = self.open_page([sse(HEAD), sse([ev("error", "done", message="RuntimeError: boom")], first_seq=7)])
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel[role=status] .rp-lost")
        self.assertEqual(page.locator("#preflight-panel [role=alert]").count(), 0)
        self.assertIn("Lost connection", page.text_content("#preflight-panel[aria-live=polite] .rp-lost"))
        page.click("#preflight-panel .rp-retry")
        page.wait_for_selector("#preflight-panel[role=status] .preflight-verdict")
        self.assertEqual(page.locator("#preflight-panel [role=alert]").count(), 0)
        self.assertIn("RuntimeError: boom", page.text_content("#preflight-panel[aria-live=polite]"))

    def test_pagehide_persisted_marks_the_cancelled_run_when_the_page_comes_back(self):
        page = self.open_page([sse(HEAD + [subject_step(1)])])
        page.route(STREAM, lambda r: None)  # never answered: the run stays live
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-cancel")
        with page.expect_request(lambda r: r.url.endswith("/api/preflight/cancel/j1")):
            page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))")
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
        page.wait_for_function("document.querySelector('#preflight-panel .rp-status').textContent.includes('page was hidden')")
        self.assertEqual(page.locator("#preflight-panel .rp-cancel").count(), 0)
        self.assertIn("text-muted", page.get_attribute("#preflight-panel .rp-status", "class"))

    def test_pageshow_without_a_hidden_cancel_changes_nothing(self):
        page = self.open_page([sse(HEAD + [subject_step(1)])])
        page.route(STREAM, lambda r: None)
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .rp-cancel")
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
        self.assertEqual(page.locator("#preflight-panel .rp-cancel").count(), 1)

    def test_pagehide_before_the_start_answers_cancels_as_soon_as_the_id_arrives_and_never_streams(self):
        page = self.fake_page()
        page.click("#btn-preflight")
        page.wait_for_function("window.starts.length === 1")
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))")
        page.evaluate("window.starts[0]()")
        page.wait_for_function("window.cancels.length === 1")
        self.assertTrue(page.evaluate("window.cancels[0]").endswith("/cancel/j1"))
        self.assertEqual(page.evaluate("window.sources.length"), 0)

    def test_cancel_before_start_returns_cancels_the_late_job(self):
        page = self.fake_page()
        page.click("#btn-preflight")
        page.wait_for_function("window.starts.length === 1")
        page.click("#preflight-panel .rp-cancel")
        page.evaluate("window.starts[0]()")
        page.wait_for_function("window.cancels.length === 1")
        self.assertTrue(page.evaluate("window.cancels[0]").endswith("/cancel/j1"))
        self.assertEqual(page.evaluate("window.sources.length"), 0)  # never streamed

    def test_second_click_racing_an_inflight_start_wins(self):
        page = self.fake_page()
        page.click("#btn-preflight")
        page.click("#btn-preflight")
        page.wait_for_function("window.starts.length === 2")
        page.evaluate("window.starts[0]()")  # the older start answers first
        page.wait_for_function("window.cancels.length === 1")
        self.assertEqual(page.evaluate("window.sources.length"), 0)
        page.evaluate("window.starts[1]()")
        page.wait_for_function("window.sources.length === 1")
        self.assertTrue(page.evaluate("window.sources[0].url").endswith("/stream/j2"))

    def test_cancel_after_finish_is_a_noop(self):
        page = self.fake_page()
        page.evaluate("""() => { window.h = ReadinessPanel.run({target: document.getElementById('preflight-panel'), body: {}});
            window.starts[0](); }""")
        page.wait_for_function("window.sources.length === 1")
        page.evaluate(self.SEND, [0, {"phase": "done", "state": "done", "seq": 0, "report": {"verdict": "ready", "checks": []}}])
        page.evaluate("window.h.cancel()")
        self.assertEqual(page.evaluate("window.cancels.length"), 0)
        self.assertNotIn("Cancelled", self.panel(page))
        self.assertTrue(page.evaluate("window.sources[0].closed"))

    def test_events_render_as_they_arrive_not_at_the_end(self):
        e = [HEAD + [subject_step(1)], [subject_step(2)], [subject_step(3), done()]]
        groups, seq = [], 0
        for grp in e:
            groups.append(sse(grp, first_seq=seq))
            seq += len(grp)
        pacer = _Pacer(groups)
        self.addCleanup(pacer.close)
        page = self.open_page([sse([])])
        page.route(STREAM, lambda r: r.continue_(url=pacer.url))
        page.click("#btn-preflight")
        page.wait_for_function("document.querySelector('#preflight-panel .rp-count')?.innerText === '1 / 3 subject checks'")
        self.assertEqual(page.locator("#preflight-panel .preflight-verdict").count(), 0)
        pacer.gates[1].set()
        page.wait_for_function("document.querySelector('#preflight-panel .rp-count')?.innerText === '2 / 3 subject checks'")
        self.assertEqual(page.locator("#preflight-panel .preflight-verdict").count(), 0)
        pacer.gates[2].set()
        page.wait_for_selector("#preflight-panel .preflight-verdict")
        self.assertIn("3 / 3 subject checks", self.panel(page))


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
            go_to_stage(page, "run")
            page.select_option("#validator-mode", "skip")
            page.click("#btn-preflight")
            page.wait_for_selector("#preflight-panel .preflight-verdict", timeout=60000)
            text = page.inner_text("#preflight-panel")
            self.assertIn("5 / 5 subject checks", text)
            states = page.eval_on_selector_all("#preflight-panel [data-phase]", "els => els.map(e => e.dataset.state)")
            self.assertTrue(states and set(states) == {"done"}, states)
            self.assertNotIn("blocked", text.lower())
            self.assertEqual(errors, [])
        finally:
            page.close()
