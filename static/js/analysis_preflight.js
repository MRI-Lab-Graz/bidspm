// analysis_preflight.js -- readiness panel: calls /api/preflight and renders the report. Logic lives in lib/preflight.py.
// Relies on globals: currentProjectId, unifiedStudyConfig, updateInternalState (all used at call time).
const VALIDATOR_KEY = `bidspm_validator_mode_${currentProjectId}`;

function validatorMode() {
    return document.getElementById('validator-mode')?.value || 'auto';
}

// Messages come from the server and contain user paths: ReadinessPanel builds DOM nodes, never innerHTML.
function renderPreflight(report) {
    const panel = document.getElementById('preflight-panel');
    if (panel) ReadinessPanel.renderReport(panel, report);
}

function runPreflight() {
    const panel = document.getElementById('preflight-panel');
    if (!panel) return;
    updateInternalState();
    ReadinessPanel.run({target: panel, body: {config: unifiedStudyConfig, validator: validatorMode()}});
}

(function () {
    document.getElementById('preflight-note').textContent =
        'Checks all subjects with the current form settings; Run checks the saved project settings and your subject selection.';
    const select = document.getElementById('validator-mode');
    try { select.value = localStorage.getItem(VALIDATOR_KEY) || 'auto'; } catch (e) { /* storage unavailable */ }
    select.addEventListener('change', () => { try { localStorage.setItem(VALIDATOR_KEY, select.value); } catch (e) { /* ignore */ } });
    document.getElementById('btn-preflight').addEventListener('click', runPreflight);
})();
