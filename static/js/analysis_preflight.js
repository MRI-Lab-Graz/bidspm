// analysis_preflight.js -- readiness panel: calls /api/preflight and renders the report. Logic lives in lib/preflight.py.
// Relies on globals: currentProjectId, unifiedStudyConfig, updateInternalState (all used at call time).
const VALIDATOR_KEY = `bidspm_validator_mode_${currentProjectId}`;

function validatorMode() {
    return document.getElementById('validator-mode')?.value || 'prism';
}

// Messages come from the server and contain user paths: build DOM nodes, never innerHTML.
function renderPreflight(report) {
    const panel = document.getElementById('preflight-panel');
    if (!panel) return;
    const tone = {blocked: 'danger', warnings: 'warning', ready: 'success'}[report.verdict] || 'secondary';
    const verdict = document.createElement('div');
    verdict.className = `alert alert-${tone} py-1 mb-1 preflight-verdict`;
    verdict.append('Readiness: ');
    const strong = document.createElement('strong');
    strong.textContent = report.verdict || 'unknown';
    verdict.append(strong);
    const list = document.createElement('ul');
    list.className = 'list-unstyled mb-0';
    for (const c of report.checks || []) {
        const li = document.createElement('li');
        li.className = `small ${c.severity === 'error' ? 'text-danger' : 'text-warning'}`;
        li.append(`${c.subject ? 'sub-' + c.subject + ': ' : ''}${c.message}`);
        if (c.fix) {
            const fix = document.createElement('div');
            fix.className = 'preflight-fix text-muted';
            fix.textContent = '→ ' + c.fix;
            li.append(fix);
        }
        list.append(li);
    }
    panel.replaceChildren(verdict, list);
}

async function runPreflight() {
    const btn = document.getElementById('btn-preflight');
    btn.disabled = true;
    try {
        updateInternalState();
        const res = await fetch('/api/preflight', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({config: unifiedStudyConfig, validator: validatorMode()})
        });
        let report;
        try { report = await res.json(); } catch (e) { throw new Error(`HTTP ${res.status}`); }
        if (!report.verdict) throw new Error(report.error || `HTTP ${res.status}`);
        renderPreflight(report);
    } catch (e) {
        renderPreflight({verdict: 'blocked', checks: [{severity: 'error', subject: null,
            message: `Readiness check failed: ${e.message}`, fix: 'Check that the server is running and try again.'}]});
    } finally {
        btn.disabled = false;
    }
}

(function () {
    const select = document.getElementById('validator-mode');
    try { select.value = localStorage.getItem(VALIDATOR_KEY) || 'prism'; } catch (e) { /* storage unavailable */ }
    select.addEventListener('change', () => { try { localStorage.setItem(VALIDATOR_KEY, select.value); } catch (e) { /* ignore */ } });
    document.getElementById('btn-preflight').addEventListener('click', runPreflight);
})();
