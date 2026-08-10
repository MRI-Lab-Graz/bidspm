// analysis_coverage_modal.js
// Extracted from templates/analysis.html — stats coverage gate and decision modal.
// Relies on globals: currentProjectId, hasProject, unifiedStudyConfig,
//   normalizeSubjectLabel, updateInternalState (defined in analysis.html as var/function).

var statsCoverageModalInstance = null;

    function getStatsCoverageModalInstance() {
        const modalEl = document.getElementById('statsCoverageModal');
        if (!modalEl) return null;
        if (!statsCoverageModalInstance) {
            statsCoverageModalInstance = new bootstrap.Modal(modalEl);
        }
        return statsCoverageModalInstance;
    }

    function fillCoverageList(listEl, lines, maxItems = 24) {
        if (!listEl) return;
        listEl.innerHTML = '';

        if (!lines.length) {
            const li = document.createElement('li');
            li.className = 'text-muted';
            li.textContent = 'none';
            listEl.appendChild(li);
            return;
        }

        lines.slice(0, maxItems).forEach(line => {
            const li = document.createElement('li');
            li.textContent = line;
            listEl.appendChild(li);
        });

        if (lines.length > maxItems) {
            const li = document.createElement('li');
            li.className = 'text-muted';
            li.textContent = `... and ${lines.length - maxItems} more`;
            listEl.appendChild(li);
        }
    }

    function renderCoverageModal(report) {
        const summary = report?.summary || {};
        const ready = Array.isArray(report?.ready_subjects) ? report.ready_subjects : [];
        const missing = Array.isArray(report?.missing_subjects) ? report.missing_subjects : [];
        const tasks = Array.isArray(report?.tasks_considered) ? report.tasks_considered : [];
        const messages = Array.isArray(report?.messages) ? report.messages : [];

        const summaryEl = document.getElementById('stats-coverage-summary');
        const tasksEl = document.getElementById('stats-coverage-tasks');
        const notesEl = document.getElementById('stats-coverage-notes');
        const readyCountEl = document.getElementById('stats-coverage-ready-count');
        const missingCountEl = document.getElementById('stats-coverage-missing-count');
        const readyListEl = document.getElementById('stats-coverage-ready-list');
        const missingListEl = document.getElementById('stats-coverage-missing-list');
        const runReadyBtn = document.getElementById('stats-coverage-run-ready');

        if (summaryEl) {
            summaryEl.textContent = `Missing data was detected for ${summary.missing_subjects || 0} of ${summary.total_subjects || 0} subjects. Choose how to proceed.`;
        }

        if (tasksEl) {
            tasksEl.textContent = tasks.length ? `Tasks checked: ${tasks.join(', ')}` : 'Tasks checked: all detected tasks';
        }

        if (notesEl) {
            notesEl.textContent = messages.length ? messages.join(' ') : 'You can continue without blocking, or run only complete subjects.';
        }

        if (readyCountEl) readyCountEl.textContent = `${ready.length} subject(s) have complete data.`;
        if (missingCountEl) missingCountEl.textContent = `${missing.length} subject(s) are missing required inputs.`;

        const readyLines = ready.map(subject => `sub-${normalizeSubjectLabel(subject)}`);
        fillCoverageList(readyListEl, readyLines);

        const missingLines = missing.map(entry => {
            const subject = normalizeSubjectLabel(entry.subject);
            const issues = Array.isArray(entry.issues) ? entry.issues.join('; ') : 'missing required inputs';
            return `sub-${subject}: ${issues}`;
        });
        fillCoverageList(missingListEl, missingLines);

        if (runReadyBtn) {
            runReadyBtn.disabled = ready.length === 0;
            runReadyBtn.textContent = (hasProject && currentProjectId)
                ? 'Continue with Ready Subjects + Save to Project'
                : 'Continue with Ready Subjects';
        }
    }

    async function openCoverageDecisionModal(report) {
        const modalEl = document.getElementById('statsCoverageModal');
        const cancelBtn = document.getElementById('stats-coverage-cancel');
        const continueAllBtn = document.getElementById('stats-coverage-continue-all');
        const runReadyBtn = document.getElementById('stats-coverage-run-ready');
        const modal = getStatsCoverageModalInstance();

        if (!modalEl || !cancelBtn || !continueAllBtn || !runReadyBtn || !modal) {
            return { action: 'cancel' };
        }

        renderCoverageModal(report);

        return await new Promise(resolve => {
            let settled = false;

            const cleanup = () => {
                cancelBtn.removeEventListener('click', onCancel);
                continueAllBtn.removeEventListener('click', onContinueAll);
                runReadyBtn.removeEventListener('click', onRunReady);
                modalEl.removeEventListener('hidden.bs.modal', onHidden);
            };

            const settle = (decision, shouldHide = true) => {
                if (settled) return;
                settled = true;
                cleanup();
                resolve(decision);
                if (shouldHide) {
                    modal.hide();
                }
            };

            const onCancel = () => settle({ action: 'cancel' });
            const onContinueAll = () => settle({ action: 'continue_all' });
            const onRunReady = () => settle({ action: 'continue_ready' });
            const onHidden = () => settle({ action: 'cancel' }, false);

            cancelBtn.addEventListener('click', onCancel);
            continueAllBtn.addEventListener('click', onContinueAll);
            runReadyBtn.addEventListener('click', onRunReady);
            modalEl.addEventListener('hidden.bs.modal', onHidden);

            modal.show();
        });
    }

    async function runStatsCoverageGate() {
        const selectedActions = Array.from(document.querySelectorAll('input[name="action"]:checked')).map(cb => cb.value);
        const checksStats = selectedActions.includes('stats') || selectedActions.includes('dataset');
        if (!checksStats) {
            return { allow: true, subjectsOverride: [] };
        }

        updateInternalState();

        const requestPayload = {
            project_id: currentProjectId || null,
            bids_dir: unifiedStudyConfig.BIDS_DIR || '',
            fmriprep_dir: unifiedStudyConfig.FMRIPREP_DIR || '',
            model_file: unifiedStudyConfig.MODELS_FILE || '',
            tasks: unifiedStudyConfig.TASKS || []
        };

        let report = null;
        try {
            const response = await fetch('/api/stats_subject_coverage', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(requestPayload)
            });
            report = await response.json();
            if (!response.ok) {
                const errMsg = report?.error || 'Unknown pre-check error';
                alert(`Stats pre-check failed: ${errMsg}\n\nExecution will continue with your current settings.`);
                return { allow: true, subjectsOverride: [] };
            }
        } catch (err) {
            alert(`Stats pre-check request failed: ${err.message}\n\nExecution will continue with your current settings.`);
            return { allow: true, subjectsOverride: [] };
        }

        const totalSubjects = Number(report?.summary?.total_subjects || 0);
        const missingSubjects = Number(report?.summary?.missing_subjects || 0);
        const readySubjects = Array.isArray(report?.ready_subjects) ? report.ready_subjects : [];

        if (totalSubjects === 0) {
            alert('Stats pre-check could not find any subjects to run. Please verify BIDS/fMRIPrep folders and subject selection.');
            return { allow: false, subjectsOverride: [] };
        }

        if (missingSubjects === 0) {
            return { allow: true, subjectsOverride: [] };
        }

        const decision = await openCoverageDecisionModal(report);
        if (decision.action === 'cancel') {
            return { allow: false, subjectsOverride: [] };
        }

        if (decision.action === 'continue_all') {
            return { allow: true, subjectsOverride: [] };
        }

        if (!readySubjects.length) {
            alert('No complete subjects are available to run with ready-only mode.');
            return { allow: false, subjectsOverride: [] };
        }

        const subjectsOverride = readySubjects.slice();
        return { allow: true, subjectsOverride };
    }
