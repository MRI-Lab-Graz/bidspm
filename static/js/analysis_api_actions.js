// analysis_api_actions.js
// Extracted from templates/analysis.html: API-backed actions: refresh tasks/spaces, validate/create/open/save model, transformer-builder launch, load latest study.
// Classic script (shared globals); loaded before the inline bootstrap script in analysis.html.

// --- API CALLS ---
async function refreshTasks() {
    const bidsDir = document.getElementById('input-BIDS_DIR')?.value;
    if (!bidsDir) return;
    const container = document.getElementById('tasks-container');
    try {
        const res = await fetch(`/get_bids_tasks?path=${encodeURIComponent(bidsDir)}`);
        const tasks = await res.json();
        container.innerHTML = '';
        if (tasks.length === 0) container.innerHTML = '<span class="text-muted x-small">No tasks found.</span>';
        tasks.forEach(t => {
            const div = document.createElement('div');
            div.className = 'form-check form-check-inline mb-0';
            div.innerHTML = `<input class="form-check-input task-checkbox" type="checkbox" value="${t}" id="task-${t}" onchange="updateInternalState(); refreshSpaces()">
                             <label class="form-check-label x-small" for="task-${t}">${t}</label>`;
            container.appendChild(div);
        });
        const modelVal = document.getElementById('input-MODELS_FILE')?.value;
        if (modelVal) refreshModelTasks();
    } catch (e) { container.innerHTML = '<span class="text-danger x-small">Error detecting tasks.</span>'; }
}

async function getModelContentFromPath(modelPath) {
    if (!modelPath) throw new Error('No model path specified');
    const response = await fetch(`/file_content?path=${encodeURIComponent(modelPath)}`);
    if (!response.ok) throw new Error('Model file not found');
    const modelText = await response.text();
    return JSON.parse(modelText);
}

async function validateModel() {
    const modelPath = document.getElementById('input-MODELS_FILE')?.value;
    const statusDiv = document.getElementById('model-validation-status');
    const icon = document.getElementById('model-validation-icon');
    const message = document.getElementById('model-validation-message');
    
    if (!modelPath) {
        statusDiv.style.display = 'none';
        return;
    }
    
    try {
        const modelContent = await getModelContentFromPath(modelPath);
        
        const validateResponse = await fetch('/validate_model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: modelContent })
        });
        
        const result = await validateResponse.json();
        statusDiv.style.display = 'block';
        
        if (result.valid) {
            icon.innerHTML = '<i class="fas fa-check-circle text-success"></i>';
            if (result.warning) {
                message.textContent = `✓ Valid (${result.warning})`;
                message.classList.add('text-warning');
            } else {
                message.textContent = '✓ Model is valid';
                message.classList.remove('text-warning');
                message.classList.add('text-success');
            }
        } else {
            icon.innerHTML = '<i class="fas fa-times-circle text-danger"></i>';
            message.textContent = `✗ ${result.error}`;
            message.classList.add('text-danger');
        }

        return { valid: !!result.valid, modelContent };
    } catch (e) {
        statusDiv.style.display = 'block';
        icon.innerHTML = '<i class="fas fa-exclamation-triangle text-warning"></i>';
        message.textContent = `Error validating model: ${e.message}`;
        message.classList.add('text-danger');
        return { valid: false, modelContent: null };
    }
}

async function createNewModel() {
    // Suggest a default path based on the current project folder or studies/
    const configFolder = document.getElementById('config-folder')?.value?.trim() || 'studies/';
    const suggestedPath = configFolder.replace(/\/$/, '') + '/model.json';

    const userPath = prompt('Save new model file to:', suggestedPath);
    if (!userPath) return;

    const trimmed = userPath.trim();
    if (!trimmed.endsWith('.json')) {
        document.getElementById('model-validation-message').textContent = 'Path must end with .json';
        document.getElementById('model-validation-status').style.display = 'block';
        return;
    }

    // Pass BIDS dir so the backend can scan tasks + trial_types
    const bidsDir = document.getElementById('input-BIDS_DIR')?.value?.trim() || '';

    async function doCreate(overwrite) {
        const resp = await fetch('/api/model/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: trimmed, bids_dir: bidsDir, overwrite })
        });
        return { resp, result: await resp.json() };
    }

    try {
        let { resp, result } = await doCreate(false);

        if (resp.status === 409) {
            if (!confirm(`File already exists:\n${trimmed}\n\nOverwrite?`)) return;
            ({ resp, result } = await doCreate(true));
        }

        if (!result.success) {
            document.getElementById('model-validation-message').textContent = result.error;
            document.getElementById('model-validation-status').style.display = 'block';
            return;
        }

        const taskInfo = result.tasks?.length
            ? `Tasks found: ${result.tasks.join(', ')}`
            : 'No tasks detected – skeleton created.';

        // Set MODELS_FILE and open editor
        const modelInput = document.getElementById('input-MODELS_FILE');
        if (modelInput) {
            modelInput.value = trimmed;
            modelInput.dispatchEvent(new Event('input', { bubbles: true }));
            modelInput.dispatchEvent(new Event('change', { bubbles: true }));
        }

        console.info(`Model created (${result.source}): ${taskInfo}`);
        await openModelEditor();

    } catch (e) {
        document.getElementById('model-validation-message').textContent = 'Failed to create model: ' + e.message;
        document.getElementById('model-validation-status').style.display = 'block';
    }
}

async function openModelEditor(options = {}) {
    const { scrollIntoView = true, showStatus = true } = options;
    const modelPath = document.getElementById('input-MODELS_FILE')?.value?.trim() || '';
    const status = document.getElementById('model-editor-status');
    const pathLabel = document.getElementById('model-editor-path');
    const workspace = document.getElementById('analysis-model-workspace-section');

    if (!modelPath) {
        modelEditorDraft = null;
        if (pathLabel) pathLabel.textContent = 'No model selected.';
        renderModelAccordionEditor();
        if (showStatus && status) {
            status.innerHTML = '<div class="alert alert-warning py-1 x-small mb-0">Set MODELS_FILE first.</div>';
        }
        if (scrollIntoView && workspace) {
            workspace.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        return;
    }

    if (status && showStatus) {
        status.innerHTML = '<div class="text-muted x-small">Loading model workspace...</div>';
    }

    try {
        const modelContent = await getModelContentFromPath(modelPath);

        modelEditorDraft = structuredClone(modelContent);
        if (pathLabel) pathLabel.textContent = modelPath;
        modelEditorOpenPaths = new Set();
        modelEditorPendingOpenPaths = new Set();

        // Pick up a transformer pipeline built in /transformer-builder and applied
        // while this page was navigated away (see openTransformerBuilder()).
        const pendingTransformerResult = consumePendingTransformerPayload(modelPath);
        if (pendingTransformerResult) {
            if (pendingTransformerResult.appliedToTargetNodes || pendingTransformerResult.staleHandoff) {
                clearPendingTransformerPayload();
                clearTransformerLaunchContext();
            }
        }

        renderModelAccordionEditor();

        // Run heavier hint scans in the background to keep first paint fast.
        Promise.allSettled([
            loadBidsTasksForModelEditor().catch(() => {
                modelEditorBidsTasks = [];
            }),
            loadInterestRegressorsForModelEditor(modelContent),
            loadGroupByOptionsForModelEditor()
        ]).then(() => {
            const latestPath = document.getElementById('input-MODELS_FILE')?.value?.trim() || '';
            if (latestPath === modelPath && modelEditorDraft) {
                renderModelAccordionEditor();
            }
        });

        if (pendingTransformerResult && status) {
            const tone = pendingTransformerResult.tone === 'success' ? 'success'
                : pendingTransformerResult.tone === 'warning' ? 'warning'
                : 'info';
            status.innerHTML = `<div class="alert alert-${tone} py-1 x-small mb-0">${pendingTransformerResult.message}</div>`;
        } else if (status && showStatus) {
            status.innerHTML = '<div class="alert alert-success py-1 x-small mb-0">Model workspace loaded.</div>';
        } else if (status && !showStatus) {
            status.innerHTML = '';
        }

        if (scrollIntoView && workspace) {
            workspace.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    } catch (e) {
        modelEditorDraft = null;
        renderModelAccordionEditor();
        if (status) {
            status.innerHTML = `<div class="alert alert-danger py-1 x-small mb-0">Could not load model: ${e.message}</div>`;
        }
        if (pathLabel) pathLabel.textContent = modelPath;
    }
}

// Indices of the model nodes whose accordion panels are open, most recently opened first.
function openNodeIndices() {
    const collectNodePaths = (paths) => Array.from(paths || [])
        .map(path => String(path || '').trim())
        .filter(path => /^Nodes\[\d+\](?:\.|$)/.test(path));
    const domOpenPaths = Array.from(document.querySelectorAll('#model-editor-accordion .accordion-collapse.show'))
        .map(el => el.dataset.jsonPath);
    return [
        ...collectNodePaths(modelEditorPendingOpenPaths),
        ...collectNodePaths(modelEditorOpenPaths),
        ...collectNodePaths(domOpenPaths),
    ].reverse().map(path => Number(path.match(/^Nodes\[(\d+)\]/)[1]));
}

function inferTransformerLaunchNodeLevel() {
    const normalizeLevel = (value) => ['Run', 'Session', 'Subject', 'Dataset']
        .find(level => level.toLowerCase() === String(value || '').trim().toLowerCase()) || '';

    for (const nodeIdx of openNodeIndices()) {
        const node = Array.isArray(modelEditorDraft?.Nodes) ? modelEditorDraft.Nodes[nodeIdx] : null;
        const level = normalizeLevel(node?.Level);
        if (level) return level;
    }

    const configuredNodeName = String(document.getElementById('input-NODE_NAME')?.value || '').trim();
    if (configuredNodeName && Array.isArray(modelEditorDraft?.Nodes)) {
        const configuredNode = modelEditorDraft.Nodes.find(node => String(node?.Name || '').trim() === configuredNodeName);
        const level = normalizeLevel(configuredNode?.Level);
        if (level) return level;
    }

    return '';
}

function inferTransformerLaunchNodeIndex() {
    const [openIdx] = openNodeIndices();
    if (openIdx !== undefined) return openIdx;

    const configuredNodeName = String(document.getElementById('input-NODE_NAME')?.value || '').trim();
    if (configuredNodeName && Array.isArray(modelEditorDraft?.Nodes)) {
        const configuredNodeIdx = modelEditorDraft.Nodes.findIndex(node => String(node?.Name || '').trim() === configuredNodeName);
        if (configuredNodeIdx >= 0) return configuredNodeIdx;
    }

    return null;
}

function persistTransformerLaunchContext(nodeLevel = '') {
    try {
        const inferredNodeLevel = inferTransformerLaunchNodeLevel();
        const inferredNodeIndex = inferTransformerLaunchNodeIndex();
        const normalizedNodeLevel = ['Run', 'Session', 'Subject', 'Dataset']
            .find(level => level.toLowerCase() === String(nodeLevel || '').trim().toLowerCase()) || '';
        const effectiveNodeLevel = normalizedNodeLevel || inferredNodeLevel;
        const launchNode = Number.isInteger(inferredNodeIndex) && Array.isArray(modelEditorDraft?.Nodes)
            ? modelEditorDraft.Nodes[inferredNodeIndex]
            : null;
        const selectedTasks = Array.isArray(modelEditorDraft?.Input?.task)
            ? Array.from(new Set(modelEditorDraft.Input.task.map(task => String(task || '').trim()).filter(Boolean)))
            : [];
        const launchSnapshotSource = (modelEditorDraft && typeof modelEditorDraft === 'object' && !Array.isArray(modelEditorDraft))
            ? modelEditorDraft
            : null;
        const payload = {
            launchId: `transformer-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
            projectId: currentProjectId || '',
            modelPath: document.getElementById('input-MODELS_FILE')?.value?.trim() || '',
            bidsDir: document.getElementById('input-BIDS_DIR')?.value?.trim() || '',
            fmriprepDir: document.getElementById('input-FMRIPREP_DIR')?.value?.trim() || '',
            modelSnapshot: launchSnapshotSource ? structuredClone(launchSnapshotSource) : null,
            launchAt: Date.now(),
            nodeIndex: Number.isInteger(inferredNodeIndex) ? inferredNodeIndex : null,
            nodeName: String(launchNode?.Name || '').trim() || null,
            inputTasks: selectedTasks,
            taskFilter: selectedTasks.length === 1 ? selectedTasks[0] : '',
            nodeLevel: effectiveNodeLevel || null,
            sourceScope: effectiveNodeLevel
                ? (effectiveNodeLevel === 'Run' ? 'events' : 'participants')
                : 'auto'
        };
        try {
            sessionStorage.setItem(TRANSFORMER_LAUNCH_CONTEXT_KEY, JSON.stringify(payload));
        } catch (withSnapshotError) {
            const fallback = { ...payload };
            delete fallback.modelSnapshot;
            try {
                sessionStorage.setItem(TRANSFORMER_LAUNCH_CONTEXT_KEY, JSON.stringify(fallback));
            } catch (fallbackError) {
                try {
                    sessionStorage.removeItem(TRANSFORMER_LAUNCH_CONTEXT_KEY);
                } catch (cleanupError) {
                    // Ignore storage cleanup failures.
                }
                throw fallbackError;
            }
        }
    } catch (e) {
        console.warn('Could not persist transformer launch context:', e);
    }
}

function openTransformerBuilder(nodeLevel = '') {
    persistTransformerLaunchContext(nodeLevel);
    const baseUrl = currentProjectId
        ? `/transformer-builder/${encodeURIComponent(currentProjectId)}`
        : '/transformer-builder';
    window.location.href = baseUrl;
}

async function saveModelEditor() {
    const modelPath = document.getElementById('input-MODELS_FILE')?.value;
    const status = document.getElementById('model-editor-status');

    if (!modelPath) {
        status.innerHTML = '<div class="alert alert-danger py-1 x-small mb-0">Set MODELS_FILE first.</div>';
        return;
    }

    if (!modelEditorDraft || typeof modelEditorDraft !== 'object') {
        status.innerHTML = '<div class="alert alert-danger py-1 x-small mb-0">No editable model loaded.</div>';
        return;
    }

    syncAllModelXHrfVariables();

    const missing = REQUIRED_ROOT_KEYS.filter(k => !(k in modelEditorDraft));
    if (missing.length) {
        status.innerHTML = `<div class="alert alert-danger py-1 x-small mb-0">Missing required keys: ${missing.join(', ')}</div>`;
        return;
    }

    if (!Array.isArray(modelEditorDraft.Input?.task) || modelEditorDraft.Input.task.length === 0) {
        status.innerHTML = '<div class="alert alert-danger py-1 x-small mb-0">Select at least one Input.task from detected BIDS tasks.</div>';
        return;
    }

    status.innerHTML = '<div class="text-muted x-small">Saving...</div>';

    try {
        const res = await fetch('/file_content', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                path: modelPath,
                content: JSON.stringify(stripLegacyGeneratedColumnsFromModel(modelEditorDraft), null, 2),
                validate_json: true
            })
        });
        const result = await res.json();
        if (!result.success) {
            status.innerHTML = `<div class="alert alert-danger py-1 x-small mb-0">${result.error}</div>`;
            return;
        }

        status.innerHTML = '<div class="alert alert-success py-1 x-small mb-0">Model saved.</div>';

        // Refresh task and hint state in the background (no await)
        refreshModelTasks();
    } catch (e) {
        status.innerHTML = `<div class="alert alert-danger py-1 x-small mb-0">Save failed: ${e.message}</div>`;
    }
}

async function refreshModelTasks() {
    const modelPath = document.getElementById('input-MODELS_FILE')?.value;
    if (!modelPath) return;
    
    await validateModel();
    
    try {
        const res = await fetch(`/get_model_tasks?path=${encodeURIComponent(modelPath)}`);
        const data = await res.json();
        
        if (data.tasks && Array.isArray(data.tasks)) {
            const checkboxes = document.querySelectorAll('.task-checkbox');
            if (checkboxes.length === 0) return;
            
            checkboxes.forEach(cb => cb.checked = false);
            
            let count = 0;
            data.tasks.forEach(t => {
                const cb = document.getElementById(`task-${t}`);
                if (cb) {
                    cb.checked = true;
                    count++;
                }
            });
            
            updateInternalState();
            refreshSpaces();

            if (count > 0) {
                 const container = document.getElementById('tasks-container');
                 const old = container.querySelector('.badge-model-sync');
                 if (old) old.remove();

                 const badge = document.createElement('span');
                 badge.className = 'badge bg-info text-dark x-small ms-2 badge-model-sync';
                 badge.innerText = 'Synced from Model';
                 container.appendChild(badge);
                 setTimeout(() => badge.remove(), 3000);
            }
        }
    } catch (e) { console.error('Error syncing model tasks:', e); }
}

async function refreshSpaces() {
    const prepDir = document.getElementById('input-FMRIPREP_DIR')?.value;
    if (!prepDir) return;
    
    const tasks = Array.from(document.querySelectorAll('.task-checkbox:checked')).map(cb => cb.value);
    let url = `/get_fmriprep_spaces?path=${encodeURIComponent(prepDir)}`;
    tasks.forEach(t => url += `&tasks=${encodeURIComponent(t)}`);
    
    try {
        const res = await fetch(url);
        const spaces = await res.json();
        const datalist = document.getElementById('spaces-list');
        datalist.innerHTML = '';
        spaces.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s;
            datalist.appendChild(opt);
        });
    } catch (e) { console.error('Error detecting spaces:', e); }
}

async function loadLatestStudy() {
    if (hasProject) return;
    
    const folder = document.getElementById('config-folder')?.value;
    const filename = document.getElementById('study-filename')?.value;
    if (!folder || !filename) return;
    
    const path = folder + filename;
    try {
        const res = await fetch(`/load_config_file?path=${encodeURIComponent(path)}`);
        unifiedStudyConfig = await res.json();
        await syncInternalToForm();
    } catch (err) { console.error('Failed to load study file:', err); }
}

function normalizeSubjectLabel(value) {
    const token = String(value || '').trim();
    if (!token) return '';
    return token.toLowerCase().startsWith('sub-') ? token.slice(4) : token;
}

document.getElementById('btn-select-participants')?.addEventListener('click', async () => {
    const statusEl = document.getElementById('participants-modal-status');
    const missingList = document.getElementById('participants-missing-list');
    const computedList = document.getElementById('participants-computed-list');
    if (statusEl) statusEl.textContent = 'Checking participant status…';
    if (missingList) missingList.innerHTML = '';
    if (computedList) computedList.innerHTML = '';

    getParticipantsModalInstance()?.show();
    updateInternalState();

    try {
        const report = await fetchParticipantsStatus();
        if (report.error) throw new Error(report.error);
        renderParticipantsModal(report);
    } catch (e) {
        if (statusEl) statusEl.textContent = `Failed to check participant status: ${e.message}`;
    }
});

document.getElementById('participantsModal')?.addEventListener('change', (e) => {
    if (e.target.classList && e.target.classList.contains('participant-checkbox')) {
        updateParticipantsSelectionHint();
    }
});

document.getElementById('participants-select-all')?.addEventListener('click', () => {
    document.querySelectorAll('.participant-checkbox').forEach(cb => { cb.checked = true; });
    updateParticipantsSelectionHint();
});
document.getElementById('participants-select-none')?.addEventListener('click', () => {
    document.querySelectorAll('.participant-checkbox').forEach(cb => { cb.checked = false; });
    updateParticipantsSelectionHint();
});
document.getElementById('participants-select-missing')?.addEventListener('click', () => {
    document.querySelectorAll('.participant-checkbox').forEach(cb => {
        const entry = findParticipantEntry(cb.value);
        cb.checked = !entry || entry.status !== 'computed';
    });
    updateParticipantsSelectionHint();
});
document.getElementById('participants-select-computed')?.addEventListener('click', () => {
    document.querySelectorAll('.participant-checkbox').forEach(cb => {
        const entry = findParticipantEntry(cb.value);
        cb.checked = !!entry && entry.status === 'computed';
    });
    updateParticipantsSelectionHint();
});
document.getElementById('participants-run-selected')?.addEventListener('click', () => applyParticipantsSelection(false));
document.getElementById('participants-force-selected')?.addEventListener('click', () => applyParticipantsSelection(true));
