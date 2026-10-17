// analysis_run.js
// Extracted from templates/analysis.html: run-issue detection from the log stream and the execution core (startExecution, resetStatus).
// Classic script (shared globals); loaded before the inline bootstrap script in analysis.html.

// --- RUN ISSUES DETECTION ---
// bidspm's own logger writes a "[HH:MM:SS] bidspm - WARNING/ERROR <tab> fnName"
// header line followed by the actual message on the next line(s), e.g.
// "No regressor found for condition ..." or "No contrast to build.".
// Those are easy to miss in a scrolling multi-thousand-line terminal, so pull
// them into a standalone summary, attributed to whichever subject is currently
// being processed, as the run streams in.
let runIssues = [];
let pendingIssueLevel = null;
let currentRunSubject = null;

function resetRunIssues() {
    runIssues = [];
    pendingIssueLevel = null;
    currentRunSubject = null;
    renderRunIssues();
}

function renderRunIssues() {
    const row = document.getElementById('run-issues-row');
    const list = document.getElementById('run-issues-list');
    const summary = document.getElementById('run-issues-summary');
    if (!row || !list || !summary) return;

    if (!runIssues.length) {
        row.classList.add('d-none');
        list.innerHTML = '';
        summary.textContent = '';
        return;
    }

    const errorCount = runIssues.filter(issue => issue.level === 'error').length;
    const warningCount = runIssues.filter(issue => issue.level === 'warning').length;
    summary.textContent = [
        errorCount ? `${errorCount} error(s)` : '',
        warningCount ? `${warningCount} warning(s)` : ''
    ].filter(Boolean).join(', ');

    list.innerHTML = runIssues.map(issue => {
        const tone = issue.level === 'error' ? 'danger' : 'warning';
        const subjectLabel = issue.subject ? `sub-${issue.subject}` : 'unknown subject';
        return `<div class="small border-start border-3 border-${tone} ps-2">
            <span class="badge bg-${tone} text-uppercase me-1">${issue.level}</span>
            <strong>${subjectLabel}</strong> &mdash; ${issue.message}
        </div>`;
    }).join('');

    row.classList.remove('d-none');
}

function processRunLogLine(line) {
    const subjectMatch = line.match(/PROCESSING SUBJECT No\.\s*:\s*\d+\s*SUBJECT LABEL\s*:\s*(\S+)/);
    if (subjectMatch) {
        currentRunSubject = subjectMatch[1];
        return;
    }

    const levelMatch = line.match(/bidspm\s*-\s*(WARNING|ERROR)\b/i);
    if (levelMatch) {
        pendingIssueLevel = levelMatch[1].toLowerCase();
        return;
    }

    const trimmed = line.trim();
    if (pendingIssueLevel && trimmed && !/^\[\d{2}:\d{2}:\d{2}\]/.test(trimmed)) {
        runIssues.push({ level: pendingIssueLevel, subject: currentRunSubject, message: trimmed });
        pendingIssueLevel = null;
        renderRunIssues();
    }
}

function parseFailedSubjects() {
    const logText = document.getElementById('terminal')?.textContent || '';
    const failedSubjects = [];
    const failRe = /(?:FAILED|Failed|❌)\s*(sub-[A-Za-z0-9]+)/g;
    let m;
    while ((m = failRe.exec(logText)) !== null) {
        if (!failedSubjects.includes(m[1])) failedSubjects.push(m[1]);
    }
    const summaryEl = document.getElementById('run-failure-summary');
    const listEl = document.getElementById('run-failure-list');
    if (summaryEl && listEl && failedSubjects.length > 0) {
        listEl.textContent = failedSubjects.join(', ');
        summaryEl.classList.remove('d-none');
    }
}

// --- EXECUTION CORE ---
async function startExecution(payload) {
    if (payload.actions.length === 0) { alert('Please select at least one action.'); return; }

    terminal.innerText = '--- EXECUTION TRIGGERED ---\n';
    document.getElementById('run-failure-summary')?.classList.add('d-none');
    execStatus.innerText = 'RUNNING';
    execStatus.className = 'badge bg-danger';
    resetRunIssues();

    payload.validator = validatorMode();
    let result;
    try {
        const res = await fetch('/run', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        try { result = await res.json(); } catch (e) { result = {error: `HTTP ${res.status} (non-JSON response)`}; }
    } catch (e) {
        result = {error: `request failed: ${e.message}`};
    }
    if (result.preflight) {
        window.analysisStages?.goTo('run');  // the report must be visible even when started from another stage
        renderPreflight(result.preflight);
        for (const c of result.preflight.checks || []) {
            terminal.innerText += `${c.severity === 'error' ? 'ERROR' : 'WARN'}: ${c.subject ? 'sub-' + c.subject + ': ' : ''}${c.message}\n`;
            if (c.fix) terminal.innerText += `  -> ${c.fix}\n`;
        }
    } else if (!result.error) {
        document.getElementById('preflight-panel')?.replaceChildren();  // drop a stale report next to a running job
    }
    if (result.error) { window.analysisStages?.goTo('run'); terminal.innerText += 'ERROR: ' + result.error + '\n'; resetStatus(); return; }

    if (result.log_file) {
        terminal.innerText += `--- FOLLOWING NOHUP LOG: ${result.log_file} ---\n`;
    }
    
    if (eventSource) eventSource.close();
    eventSource = new EventSource(`/stream/${result.execution_id}`);
    eventSource.onmessage = e => {
        terminal.innerText += e.data + '\n';
        terminal.scrollTop = terminal.scrollHeight;
        processRunLogLine(e.data);
        if (e.data.includes('Process finished')) { parseFailedSubjects(); resetStatus(); }
    };
    eventSource.onerror = () => {
        terminal.innerText += '\n--- LOG STREAM INTERRUPTED ---\n';
        parseFailedSubjects();
        resetStatus();
    };
}

function resetStatus() { 
    execStatus.innerText = 'IDLE'; 
    execStatus.className = 'badge bg-secondary';
    if (eventSource) eventSource.close();
}
