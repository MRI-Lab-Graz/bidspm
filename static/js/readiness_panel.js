// readiness_panel.js -- live readiness check: starts a preflight job and renders its SSE progress into a target element.
// Server messages contain user paths: everything goes into the DOM via textContent, never innerHTML.
window.ReadinessPanel = (function () {
    const PHASES = [['folders', 'Folders'], ['validator', 'Dataset validator'], ['model', 'Model'], ['subjects', 'Subjects']];
    const GLYPH = {pending: '○', running: '…', done: '✓'};
    let runSeq = 0;
    let current = null;

    function el(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined) e.textContent = text;
        return e;
    }

    function reportNodes(report) {
        const tone = {blocked: 'danger', warnings: 'warning', ready: 'success'}[report.verdict] || 'secondary';
        const verdict = el('div', `alert alert-${tone} py-1 mb-1 preflight-verdict`, 'Readiness: ');
        if (report.failed) verdict.setAttribute('role', 'alert');
        verdict.append(el('strong', '', report.verdict || 'unknown'));
        const list = el('ul', 'list-unstyled mb-0');
        for (const c of report.checks || []) list.append(itemNode(c));
        return [verdict, list];
    }

    function itemNode(c) {
        const li = el('li', `small ${c.severity === 'error' ? 'text-danger' : 'text-warning'}`);
        li.append(`${c.subject ? 'sub-' + c.subject + ': ' : ''}${c.message}`);
        if (c.fix) li.append(el('div', 'preflight-fix text-muted', '→ ' + c.fix));
        return li;
    }

    function renderReport(target, report) {
        target.replaceChildren(...reportNodes(report));
    }

    function failure(message, fix) {
        const check = {severity: 'error', subject: null, message: `Readiness check failed: ${message}`};
        if (fix) check.fix = fix;
        return {verdict: 'blocked', failed: true, checks: [check]};
    }
    const TRY_AGAIN = 'Check that the server is running and try again.';

    function post(url, body) {
        return fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
    }
    const cancelUrl = (id) => `/api/preflight/cancel/${encodeURIComponent(id)}`;
    const MAX_LIVE_ITEMS = 200;
    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

    function run({target, body, onDone}) {
        if (current) current.cancel();
        const mine = ++runSeq;
        let stopped = false, jobId = null, source = null, lastSeq = -1, finished = false, subjectsTotal = 0;
        let errors = 0, warnings = 0, shown = 0, attached = target.isConnected;
        const collected = [];
        const live = () => mine === runSeq && !stopped;

        // One persistent live region: verdict, failure and connection notices are announced from inside it.
        target.setAttribute('role', 'status');
        target.setAttribute('aria-live', 'polite');
        const phaseEls = new Map();
        const phaseList = el('ul', 'list-unstyled mb-1 small rp-phases');
        for (const [key, label] of PHASES) {
            const li = el('li', 'rp-phase');
            li.dataset.phase = key;
            const glyph = el('span', 'rp-glyph me-1');
            glyph.setAttribute('aria-hidden', 'true');
            li.append(glyph, label, el('span', 'visually-hidden rp-state'));
            li.hidden = key === 'validator';  // shown once the validator actually runs
            phaseList.append(li);
            phaseEls.set(key, li);
            setPhase(key, 'pending');
        }
        const status = el('div', 'small text-muted rp-status', 'Checking readiness...');
        const bar = el('div', 'progress mb-1 rp-bar');
        bar.hidden = true;
        bar.setAttribute('role', 'progressbar');
        bar.setAttribute('aria-label', 'Readiness check progress');
        bar.setAttribute('aria-valuemin', '0');
        bar.setAttribute('aria-valuemax', '100');
        const barFill = el('div', 'progress-bar');
        bar.append(barFill);
        const count = el('div', 'small rp-count');
        count.title = 'One check per subject and task: subjects x tasks';
        const counts = el('div', 'small fw-semibold rp-counts');
        const items = el('ul', 'list-unstyled mb-1 rp-items');
        items.style.cssText = 'max-height: 12rem; overflow-y: auto;';
        const more = el('li', 'small text-muted rp-more');
        const cancelBtn = el('button', 'btn btn-sm btn-outline-secondary rp-cancel', 'Cancel');
        cancelBtn.type = 'button';
        const notice = el('div', 'rp-notice');
        const root = el('div', 'rp-root');
        // Progress details change on every event: keep them out of the live region so only the verdict/notices are announced.
        const progress = el('div', 'rp-progress');
        progress.setAttribute('aria-live', 'off');
        progress.append(phaseList, bar, count, counts, items);
        root.append(status, progress, notice, cancelBtn);
        target.replaceChildren(root);

        function setPhase(key, state) {
            const li = phaseEls.get(key);
            li.dataset.state = state;
            li.querySelector('.rp-glyph').textContent = GLYPH[state];
            li.querySelector('.rp-state').textContent = ` (${state})`;
            if (state !== 'pending') li.hidden = false;
        }

        function setBar(mode, pct) {
            bar.hidden = mode === 'hidden';
            barFill.classList.toggle('progress-bar-striped', mode === 'indeterminate');
            barFill.classList.toggle('progress-bar-animated', mode === 'indeterminate');
            const clamped = Math.max(0, Math.min(100, pct || 0));
            barFill.style.width = mode === 'indeterminate' ? '100%' : `${clamped}%`;
            if (mode === 'determinate') bar.setAttribute('aria-valuenow', String(Math.round(clamped)));
            else bar.removeAttribute('aria-valuenow');
        }

        function addItems(list) {
            for (const c of list || []) {
                collected.push(c);
                if (c.severity === 'error') errors++; else warnings++;
                if (shown < MAX_LIVE_ITEMS) { items.append(itemNode(c)); shown++; }
            }
            counts.textContent = collected.length ? `${plural(errors, 'error')}, ${plural(warnings, 'warning')}` : '';
            if (collected.length > shown) {
                more.textContent = `+${collected.length - shown} more (see the final report)`;
                items.append(more);
            }
        }

        // Reload/navigation: free the server slot of a live job (beacons survive the unload, plain fetches may not).
        function onPageHide() {
            if (!jobId || finished || stopped) return;
            const url = cancelUrl(jobId);
            if (!(navigator.sendBeacon && navigator.sendBeacon(url))) fetch(url, {method: 'POST', keepalive: true}).catch(() => {});
        }
        window.addEventListener('pagehide', onPageHide);

        function end() {
            window.removeEventListener('pagehide', onPageHide);
            finished = true;
            if (source) source.close();
            source = null;
        }

        function showFailure(message, fix, freeSlot = true) {
            end();
            if (jobId && freeSlot) post(cancelUrl(jobId)).catch(() => {});  // free the server slot of a job that errored
            renderReport(target, failure(message, fix));
        }

        function showLost() {
            if (source) source.close();
            source = null;
            const retry = el('button', 'btn btn-sm btn-outline-primary ms-2 rp-retry', 'Retry');
            retry.type = 'button';
            retry.addEventListener('click', () => { if (live()) connect(); });
            const lost = el('div', 'alert alert-warning py-1 mb-1 rp-lost', 'Lost connection to the server.');
            lost.setAttribute('role', 'alert');
            lost.append(retry);
            notice.replaceChildren(lost);
        }

        function handle(ev) {
            if (typeof ev.seq === 'number') {
                if (ev.seq <= lastSeq) return;  // replay overlap after a reconnect
                lastSeq = ev.seq;
            }
            if (ev.phase === 'error') {
                // A stream-lifetime timeout has state "done" but no seq: the job may still run, so offer Retry.
                if (ev.state === 'done' && typeof ev.seq !== 'number') return showLost();
                return showFailure(ev.message || 'unknown error', '', ev.message !== 'job not found');
            }
            if (ev.phase === 'done') return finish(ev);
            if (!phaseEls.has(ev.phase)) return;
            if (ev.phase === 'subjects') {
                subjectsTotal = ev.total || subjectsTotal;
                if (ev.index) count.textContent = `${ev.index} / ${subjectsTotal} subject checks`;
            }
            if (ev.state === 'done') setPhase(ev.phase, 'done');
            else if (ev.state === 'start' || ev.state === 'progress') setPhase(ev.phase, 'running');
            if (subjectsTotal) {
                if (ev.index != null) setBar('determinate', 100 * ev.index / subjectsTotal);
                else if (ev.phase === 'subjects' && ev.state === 'done') {
                    // all subjects are checked: a still-running validator is the only thing left to wait for
                    if (phaseEls.get('validator').dataset.state === 'running') setBar('indeterminate');
                    else setBar('determinate', 100);
                }
            } else if (phaseEls.get('validator').dataset.state === 'running') setBar('indeterminate');
            else setBar('hidden');
            addItems(ev.items);
        }

        function finish(ev) {
            end();
            const report = ev.report || {verdict: ev.verdict, checks: collected};
            for (const [key, li] of phaseEls) { if (li.hidden) li.remove(); else setPhase(key, 'done'); }
            status.remove(); bar.remove(); counts.remove(); items.remove(); notice.remove(); cancelBtn.remove();
            progress.after(...reportNodes(report));
            if (onDone) {
                try { onDone(report); } catch (e) { console.error('ReadinessPanel onDone failed', e); }
            }
        }

        function connect() {
            notice.replaceChildren();
            const url = `/api/preflight/stream/${encodeURIComponent(jobId)}` + (lastSeq >= 0 ? `?from=${lastSeq + 1}` : '');
            source = new EventSource(url);
            source.onmessage = (m) => {
                if (!live() || finished) return;
                if (target.isConnected) attached = true;
                else if (attached) return abandon();  // the page moved on: stop streaming and free the server slot
                let ev;
                try { ev = JSON.parse(m.data); } catch (e) { return; }
                handle(ev);
            };
            source.onerror = () => {
                if (!live() || finished) return;
                showLost();
            };
        }

        function abandon() {
            window.removeEventListener('pagehide', onPageHide);
            stopped = true;
            if (source) source.close();
            source = null;
            if (jobId) postCancel(jobId);
        }

        function cancel() {
            if (stopped || finished) return;
            abandon();
            notice.replaceChildren();
            cancelBtn.remove(); bar.remove();
            status.textContent = 'Cancelled';
        }

        function postCancel(id) {
            post(cancelUrl(id)).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); }).catch(() => {
                if (mine === runSeq) status.textContent = 'Could not cancel the check on the server';
            });
        }
        cancelBtn.addEventListener('click', cancel);
        const handle_ = {cancel};
        current = handle_;

        (async () => {
            try {
                const res = await post('/api/preflight/start', body);
                let data = null;
                try { data = await res.json(); } catch (e) { /* non-JSON body */ }
                if (!live()) {  // cancelled or superseded while the start request was in flight
                    if (data && data.id) { jobId = data.id; postCancel(data.id); }
                    return;
                }
                if (!res.ok || !data || !data.id) {
                    return showFailure((data && data.error) || `HTTP ${res.status}`, data && data.error ? '' : TRY_AGAIN);
                }
                jobId = data.id;
                connect();
            } catch (e) {
                if (live()) showFailure(e.message, TRY_AGAIN);
            }
        })();
        return handle_;
    }

    return {run, renderReport};
})();
