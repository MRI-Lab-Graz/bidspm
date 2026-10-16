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
        return {verdict: 'blocked', checks: [check]};
    }
    const TRY_AGAIN = 'Check that the server is running and try again.';

    function post(url, body) {
        return fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
    }

    function run({target, body, onDone}) {
        if (current) current.cancel();
        const mine = ++runSeq;
        const live = () => mine === runSeq && !stopped;
        let stopped = false, jobId = null, source = null, lastSeq = -1, finished = false, subjectsTotal = 0;
        let errors = 0, warnings = 0;
        const collected = [];

        const phaseEls = {};
        const phaseList = el('ul', 'list-unstyled mb-1 small rp-phases');
        for (const [key, label] of PHASES) {
            const li = el('li', 'rp-phase');
            li.dataset.phase = key;
            li.append(el('span', 'rp-glyph me-1'), label);
            li.hidden = key === 'validator';  // shown once the validator actually runs
            phaseList.append(li);
            phaseEls[key] = li;
            setPhase(key, 'pending');
        }
        const status = el('div', 'small text-muted rp-status', 'Checking readiness...');
        status.setAttribute('role', 'status');
        const bar = el('div', 'progress mb-1 rp-bar');
        bar.hidden = true;
        const barFill = el('div', 'progress-bar');
        barFill.setAttribute('role', 'progressbar');
        barFill.setAttribute('aria-label', 'Readiness check progress');
        bar.append(barFill);
        const count = el('div', 'small rp-count');
        const counts = el('div', 'small fw-semibold rp-counts');
        const items = el('ul', 'list-unstyled mb-1 rp-items');
        const cancelBtn = el('button', 'btn btn-sm btn-outline-secondary rp-cancel', 'Cancel');
        cancelBtn.type = 'button';
        const notice = el('div', 'rp-notice');
        const root = el('div', 'rp-root');
        root.append(status, phaseList, bar, count, counts, items, notice, cancelBtn);
        target.replaceChildren(root);

        function setPhase(key, state) {
            phaseEls[key].dataset.state = state;
            phaseEls[key].firstChild.textContent = GLYPH[state];
            if (state !== 'pending') phaseEls[key].hidden = false;
        }

        function setBar(mode, pct) {
            bar.hidden = mode === 'hidden';
            barFill.classList.toggle('progress-bar-striped', mode === 'indeterminate');
            barFill.classList.toggle('progress-bar-animated', mode === 'indeterminate');
            barFill.style.width = mode === 'indeterminate' ? '100%' : `${pct || 0}%`;
            if (mode === 'determinate') barFill.setAttribute('aria-valuenow', String(Math.round(pct)));
            else barFill.removeAttribute('aria-valuenow');
        }

        function addItems(list) {
            for (const c of list || []) {
                collected.push(c);
                if (c.severity === 'error') errors++; else warnings++;
                items.append(itemNode(c));
            }
            const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
            counts.textContent = collected.length ? `${plural(errors, 'error')}, ${plural(warnings, 'warning')}` : '';
        }

        function end() {
            finished = true;
            if (source) source.close();
            source = null;
        }

        function showFailure(message, fix) {
            end();
            renderReport(target, failure(message, fix));
        }

        function handle(ev) {
            if (typeof ev.seq === 'number') lastSeq = ev.seq;
            if (ev.phase === 'error') return showFailure(ev.message || 'unknown error');
            if (ev.phase === 'done') return finish(ev);
            if (!phaseEls[ev.phase]) return;
            if (ev.phase === 'subjects') {
                subjectsTotal = ev.total || subjectsTotal;
                if (ev.index) count.textContent = `${ev.index} / ${subjectsTotal} subjects`;
            }
            if (ev.state === 'done') setPhase(ev.phase, 'done');
            else if (ev.state === 'start' || ev.state === 'progress') setPhase(ev.phase, 'running');
            if (subjectsTotal) setBar('determinate', 100 * (ev.index || 0) / subjectsTotal);
            else if (phaseEls.validator.dataset.state === 'running') setBar('indeterminate');
            else setBar('hidden');
            addItems(ev.items);
        }

        function finish(ev) {
            end();
            const report = ev.report || {verdict: ev.verdict, checks: collected};
            for (const key in phaseEls) { if (phaseEls[key].hidden) phaseEls[key].remove(); else setPhase(key, 'done'); }
            status.remove(); bar.remove(); counts.remove(); items.remove(); notice.remove(); cancelBtn.remove();
            root.append(...reportNodes(report));
            if (onDone) onDone(report);
        }

        function connect() {
            notice.replaceChildren();
            const url = `/api/preflight/stream/${encodeURIComponent(jobId)}` + (lastSeq >= 0 ? `?from=${lastSeq + 1}` : '');
            source = new EventSource(url);
            source.onmessage = (m) => {
                if (!live() || finished) return;
                let ev;
                try { ev = JSON.parse(m.data); } catch (e) { return; }
                handle(ev);
            };
            source.onerror = () => {
                if (!live() || finished) return;
                if (source) source.close();
                source = null;
                const retry = el('button', 'btn btn-sm btn-outline-primary ms-2 rp-retry', 'Retry');
                retry.type = 'button';
                retry.addEventListener('click', () => { if (live()) connect(); });
                const lost = el('div', 'alert alert-warning py-1 mb-1 rp-lost', 'Lost connection to the server.');
                lost.append(retry);
                notice.replaceChildren(lost);
            };
        }

        function cancel() {
            if (stopped || finished) return;
            stopped = true;
            if (source) source.close();
            source = null;
            if (jobId) post(`/api/preflight/cancel/${encodeURIComponent(jobId)}`).catch(() => {});
            if (mine === runSeq) {
                cancelBtn.remove(); bar.remove();
                status.textContent = 'Cancelled';
            }
        }
        cancelBtn.addEventListener('click', cancel);
        const handle_ = {cancel};
        current = handle_;

        (async () => {
            try {
                const res = await post('/api/preflight/start', body);
                let data = null;
                try { data = await res.json(); } catch (e) { /* non-JSON body */ }
                if (stopped) { if (data && data.id) post(`/api/preflight/cancel/${encodeURIComponent(data.id)}`).catch(() => {}); return; }
                if (mine !== runSeq) return;
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
