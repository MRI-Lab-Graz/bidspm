// analysis_participants_modal.js
// Extracted from templates/analysis.html — participant selection modal functions.
// Relies on globals: currentProjectId, unifiedStudyConfig (defined in analysis.html as var).

var participantsModalInstance = null;
var participantsStatusReport = null;
// null = no explicit selection (run all participants); Set = explicit subject id override.
var selectedParticipants = null;

    function getParticipantsModalInstance() {
        const modalEl = document.getElementById('participantsModal');
        if (!modalEl) return null;
        if (!participantsModalInstance) {
            participantsModalInstance = new bootstrap.Modal(modalEl);
        }
        return participantsModalInstance;
    }

    function updateParticipantsSummary() {
        const el = document.getElementById('participants-summary');
        if (!el) return;
        el.textContent = selectedParticipants
            ? `${selectedParticipants.size} participant(s) selected`
            : 'All participants';
    }

    function updateParticipantsSelectionHint() {
        const hint = document.getElementById('participants-selection-hint');
        if (!hint) return;
        const checked = document.querySelectorAll('.participant-checkbox:checked').length;
        const total = document.querySelectorAll('.participant-checkbox').length;
        hint.textContent = `${checked} of ${total} selected`;
    }

    async function fetchParticipantsStatus() {
        const actions = Array.from(document.querySelectorAll('input[name="action"]:checked')).map(cb => cb.value);
        const payload = {
            project_id: currentProjectId || null,
            bids_dir: unifiedStudyConfig.BIDS_DIR || '',
            fmriprep_dir: unifiedStudyConfig.FMRIPREP_DIR || '',
            derivatives_dir: unifiedStudyConfig.DERIVATIVES_DIR || unifiedStudyConfig.WD || '',
            model_file: unifiedStudyConfig.MODELS_FILE || '',
            tasks: unifiedStudyConfig.TASKS || [],
            actions: actions,
            space: unifiedStudyConfig.SPACE || 'MNI152NLin2009cAsym',
            fwhm: Number.isFinite(unifiedStudyConfig.FWHM) ? unifiedStudyConfig.FWHM : 6
        };
        const response = await fetch('/api/participants_status', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        return await response.json();
    }

    // Built from DOM properties, never markup: the subject id (a folder name) must reach selectedParticipants unchanged.
    function participantRow(entry, index) {
        const subject = entry.subject;
        const row = document.createElement('div');
        row.className = 'form-check';
        const box = document.createElement('input');
        box.className = 'form-check-input participant-checkbox';
        box.type = 'checkbox';
        box.value = subject;
        box.id = `participant-row-${index}`;
        box.checked = selectedParticipants ? selectedParticipants.has(subject) : entry.status !== 'computed';
        const label = document.createElement('label');
        label.className = 'form-check-label small';
        label.htmlFor = box.id;
        label.title = Array.isArray(entry.pending) && entry.pending.length ? `Pending: ${entry.pending.join(', ')}` : '';
        label.textContent = `sub-${subject}`;
        row.append(box, label);
        return row;
    }

    function fillParticipantList(list, entries) {
        if (!list) return;
        list.textContent = '';
        if (!entries.length) {
            list.innerHTML = '<span class="small text-muted">none</span>';
            return;
        }
        entries.forEach((entry, index) => list.appendChild(participantRow(entry, index)));
    }

    function renderParticipantsModal(report) {
        participantsStatusReport = report;
        const statusEl = document.getElementById('participants-modal-status');
        const missingList = document.getElementById('participants-missing-list');
        const computedList = document.getElementById('participants-computed-list');
        const missingCountEl = document.getElementById('participants-missing-count');
        const computedCountEl = document.getElementById('participants-computed-count');

        const details = Array.isArray(report.details) ? report.details : [];

        if (!details.length) {
            if (statusEl) statusEl.textContent = 'No participants detected. Check the BIDS/fMRIPrep folder paths.';
        } else if (!report.evaluable) {
            if (statusEl) statusEl.textContent = 'Select Smooth/Stats actions and at least one task to see computed status. Showing all detected participants.';
        } else {
            const tasksLabel = (report.tasks_considered || []).join(', ') || 'auto-detected';
            const actionsLabel = (report.actions_considered || []).join(', ') || 'n/a';
            if (statusEl) statusEl.textContent = `Tasks checked: ${tasksLabel}. Actions checked: ${actionsLabel}.`;
        }

        const missingEntries = details.filter(d => d.status !== 'computed');
        const computedEntries = details.filter(d => d.status === 'computed');

        fillParticipantList(missingList, missingEntries);
        fillParticipantList(computedList, computedEntries);
        if (missingCountEl) missingCountEl.textContent = `(${missingEntries.length})`;
        if (computedCountEl) computedCountEl.textContent = `(${computedEntries.length})`;

        updateParticipantsSelectionHint();
    }

    function findParticipantEntry(subject) {
        return (participantsStatusReport?.details || []).find(d => d.subject === subject);
    }

    function applyParticipantsSelection(force) {
        const checked = Array.from(document.querySelectorAll('.participant-checkbox:checked')).map(cb => cb.value);
        const total = document.querySelectorAll('.participant-checkbox').length;

        if (checked.length === 0) {
            alert('Select at least one participant.');
            return;
        }

        selectedParticipants = checked.length < total ? new Set(checked) : null;

        if (force) {
            const forceCb = document.getElementById('force');
            if (forceCb) forceCb.checked = true;
        }

        updateParticipantsSummary();
        getParticipantsModalInstance()?.hide();
    }
