// analysis_project_form.js
// Extracted from templates/analysis.html: form data get/set, project config load/save, static listeners, internal-state sync.
// Classic script (shared globals); loaded before the inline bootstrap script in analysis.html.

// --- FORM DATA HANDLERS ---
function getFullFormData() {
    const actions = Array.from(document.querySelectorAll('input[name="action"]:checked')).map(cb => cb.value);
    return {
        actions: actions,
        pilot: document.getElementById('pilot').checked,
        force: document.getElementById('force').checked,
        run_results: document.getElementById('run_results').checked,
        estimation_engine: document.getElementById('estimation_engine').value,
        skip_validation: document.getElementById('skip_validation').checked,
        stats_workers: Number(document.getElementById('stats_workers')?.value) || 4,
        project_id: currentProjectId || null,
        config_folder: hasProject ? null : document.getElementById('config-folder')?.value,
        study_filename: hasProject ? null : document.getElementById('study-filename')?.value,
        study_content: unifiedStudyConfig,
        bms_model_files: Array.from(document.querySelectorAll('#bms-model-list input')).map(i => i.value.trim()).filter(Boolean),
        node_name: (document.getElementById('run_node_name')?.value || '').trim() || null
    };
}

async function setFullFormData(data) {
    if (!data) return;
    
    // Checklist Actions
    document.querySelectorAll('input[name="action"]').forEach(cb => {
        cb.checked = data.actions && data.actions.includes(cb.value);
    });
    
    // Switches & Text
    const fields = [];
    if (!hasProject) fields.push('config-folder', 'study-filename');
    fields.forEach(f => {
        const el = document.getElementById(f);
        if (el && data[f]) el.value = data[f];
    });

    const engineSelect = document.getElementById('estimation_engine');
    if (engineSelect && data.estimation_engine) engineSelect.value = data.estimation_engine;

    const statsWorkersInput = document.getElementById('stats_workers');
    if (statsWorkersInput && data.stats_workers) statsWorkersInput.value = data.stats_workers;

    const switches = ['pilot', 'force', 'run_results', 'skip_validation'];
    switches.forEach(s => {
        const el = document.getElementById(s);
        if (el && data[s] !== undefined) el.checked = data[s];
    });

    if (data.study_content) {
        unifiedStudyConfig = data.study_content;
        await syncInternalToForm();
    }
}

document.getElementById('suggest_workers')?.addEventListener('click', async () => {
    const hint = document.getElementById('suggest_workers_hint');
    try {
        const r = await (await fetch('/api/suggested_workers')).json();
        document.getElementById('stats_workers').value = r.suggested;
        const mem = r.mem_available_gb ? `, ${Math.round(r.mem_available_gb)} GB free` : '';
        hint.textContent = `Suggested ${r.suggested} for this machine (${r.cpus} cores${mem}; about 4 GB per worker on long scans).`;
    } catch (e) {
        hint.textContent = 'Could not read this machine\'s resources.';
    }
});

// --- STATIC FORM INITIALIZATION ---
async function initApp() {
    try {
        const res = await fetch('/get_schema');
        schema = await res.json();
        setupStaticListeners();
        
        // Load project config if we have a project
        if (hasProject && currentProjectId) {
            await loadProjectConfig();
        } else {
            await loadLatestStudy();
        }

        if (document.getElementById('input-MODELS_FILE')?.value) {
            await openModelEditor({ scrollIntoView: false, showStatus: false });
            refreshModelTasks();
        }
    } catch (err) { console.error('App init failed:', err); }
}

async function loadProjectConfig() {
    try {
        const res = await fetch(`/api/projects/${currentProjectId}/export`);
        const config = await res.json();

        // A fresh/different project invalidates any participant selection made
        // against the previous project's subjects.
        selectedParticipants = null;
        updateParticipantsSummary();

        // Map the config to the unified format
        unifiedStudyConfig = {
            WD: config.WD || '',
            BIDS_DIR: config.BIDS_DIR || '',
            DERIVATIVES_DIR: config.DERIVATIVES_DIR || '',
            FMRIPREP_DIR: config.FMRIPREP_DIR || '',
            MODELS_FILE: config.MODELS_FILE || '',
            NODE_NAME: config.NODE_NAME || '',
            SPACE: config.SPACE || 'MNI152NLin2009cAsym',
            FWHM: config.FWHM || 6,
            TASKS: config.TASKS || [],
            VERBOSITY: config.VERBOSITY || 2,
            container_type: config.container_type || 'docker',
            docker_image: config.docker_image || 'bidspm/bidspm:latest',
            apptainer_image: config.apptainer_image || '/path/to/your/bidspm.sif',
            spm_standalone_image: config.spm_standalone_image || ''
        };
        
        await syncInternalToForm();
    } catch (err) {
        console.error('Failed to load project config:', err);
    }
}

async function saveProjectConfig() {
    if (!currentProjectId) return;
    
    updateInternalState();
    
    // Map back to project config format
    const config = {
        bids_folder: unifiedStudyConfig.BIDS_DIR || '',
        derivatives_folder: unifiedStudyConfig.DERIVATIVES_DIR || '',
        fmriprep_folder: unifiedStudyConfig.FMRIPREP_DIR || '',
        output_folder: unifiedStudyConfig.WD || '',
        models_file: unifiedStudyConfig.MODELS_FILE || '',
        node_name: unifiedStudyConfig.NODE_NAME || '',
        space: unifiedStudyConfig.SPACE || 'MNI152NLin2009cAsym',
        fwhm: parseFloat(unifiedStudyConfig.FWHM) || 6,
        tasks: unifiedStudyConfig.TASKS || [],
        verbosity: parseInt(unifiedStudyConfig.VERBOSITY) || 2,
        container_type: unifiedStudyConfig.container_type || 'docker',
        docker_image: unifiedStudyConfig.docker_image || 'bidspm/bidspm:latest',
        apptainer_image: unifiedStudyConfig.apptainer_image || '/path/to/your/bidspm.sif',
        spm_standalone_image: unifiedStudyConfig.spm_standalone_image || '',
        actions: Array.from(document.querySelectorAll('input[name="action"]:checked')).map(cb => cb.value),
        pilot: document.getElementById('pilot').checked,
        skip_validation: true
    };
    
    try {
        await fetch(`/api/projects/${currentProjectId}/config`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        });
    } catch (err) {
        console.error('Failed to save project config:', err);
    }
}

function setupStaticListeners() {
    // Browse buttons for Settings
    document.querySelectorAll('.btn-browse').forEach(btn => {
        btn.onclick = () => openBrowser(btn.dataset.key, btn.dataset.type === 'dir');
    });
    
    // Browse buttons for Container
    document.querySelectorAll('.btn-browse-container').forEach(btn => {
        btn.onclick = () => openBrowser(btn.dataset.key, btn.dataset.type === 'dir', 'container');
    });
    
    // Input changes for Settings
    document.querySelectorAll('.dynamic-input').forEach(input => {
        input.onchange = updateInternalState;
    });
    
    // Input changes for Container
    document.querySelectorAll('.container-input').forEach(input => {
        input.onchange = updateInternalState;
    });

    // Container type radios
    document.querySelectorAll('.container-type-radio').forEach(radio => {
        radio.onchange = (e) => {
            const type = e.target.value;
            document.getElementById('docker-options').classList.toggle('d-none', type !== 'docker');
            document.getElementById('apptainer-options').classList.toggle('d-none', type !== 'apptainer');
            updateInternalState();
        };
    });

    // BMS checkbox show/hide model file list
    const bmsCheckbox = document.getElementById('bms');
    if (bmsCheckbox) {
        bmsCheckbox.addEventListener('change', () => {
            document.getElementById('bms-models-section').classList.toggle('d-none', !bmsCheckbox.checked);
        });
    }
    document.getElementById('btn-add-bms-model')?.addEventListener('click', () => {
        const row = document.createElement('div');
        row.className = 'd-flex gap-1 align-items-center bms-model-row';
        row.innerHTML = '<input type="text" class="form-control form-control-sm" placeholder="/path/to/model_smdl.json"><button type="button" class="btn btn-outline-danger btn-sm bms-model-remove">×</button>';
        row.querySelector('.bms-model-remove').addEventListener('click', () => row.remove());
        document.getElementById('bms-model-list').appendChild(row);
    });

    // Node-name input: show resolved output folder as a hint
    const runNodeNameInput = document.getElementById('run_node_name');
    if (runNodeNameInput) {
        const hintEl = document.getElementById('run-node-output-hint');
        const pathEl = document.getElementById('run-node-output-path');
        const _FFX_UNNAMED = new Set(['run', 'runlevel']);
        function updateNodeHint() {
            const name = runNodeNameInput.value.trim();
            if (!name || !hintEl || !pathEl) { hintEl && hintEl.style.setProperty('display', 'none'); return; }
            const normalized = name.toLowerCase().replace(/[^a-z0-9]/g, '');
            const suffix = _FFX_UNNAMED.has(normalized) ? '' : `_node-${name}`;
            pathEl.textContent = `derivatives/bidspm-stats/sub-*${suffix}/`;
            hintEl.style.removeProperty('display');
        }
        runNodeNameInput.addEventListener('input', updateNodeHint);
        updateNodeHint();
    }

    // BIDS directory change triggers task detection
    const bidsInput = document.getElementById('input-BIDS_DIR');
    if (bidsInput) bidsInput.addEventListener('change', async () => {
        await refreshTasks();
        modelEditorBidsTasks = [];
        modelEditorInterestRegressors = [];
        modelEditorGroupByOptions = ['subject'];
    });

    // Models file change triggers model workspace reload and background validation/sync
    const modelInput = document.getElementById('input-MODELS_FILE');
    if (modelInput) modelInput.addEventListener('change', async () => {
        // Persist the new path so it survives page reloads (e.g. returning from transformer builder).
        if (hasProject && currentProjectId) await saveProjectConfig();
        await openModelEditor({ scrollIntoView: false, showStatus: false });
        refreshModelTasks();
    });

    const btnCreateModel = document.getElementById('btn-create-model');
    if (btnCreateModel) btnCreateModel.addEventListener('click', createNewModel);

    const btnSaveModel = document.getElementById('btn-save-model-editor');
    if (btnSaveModel) btnSaveModel.addEventListener('click', saveModelEditor);

    const pathToggle = document.getElementById('model-show-paths');
    if (pathToggle) {
        pathToggle.addEventListener('change', (e) => {
            showModelTechnicalPaths = e.target.checked;
            if (modelEditorDraft) renderModelAccordionEditor();
        });
    }

    const advancedToggle = document.getElementById('model-show-advanced');
    if (advancedToggle) {
        advancedToggle.checked = showModelAdvancedFields;
        advancedToggle.addEventListener('change', (e) => {
            showModelAdvancedFields = e.target.checked;
            localStorage.setItem(MODEL_ADVANCED_FIELDS_STORAGE_KEY, showModelAdvancedFields ? '1' : '0');
            if (modelEditorDraft) renderModelAccordionEditor();
        });
    }

    // FMRIPREP directory change triggers space detection
    const prepInput = document.getElementById('input-FMRIPREP_DIR');
    if (prepInput) prepInput.addEventListener('change', refreshSpaces);
    
    // Config folder browser (only when no project)
    if (!hasProject) {
        document.querySelectorAll('.btn-browse-folder').forEach(btn => {
            btn.onclick = () => openBrowser('config-folder', true);
        });
    }
}

function updateInternalState() {
    // Settings details
    document.querySelectorAll('.dynamic-input').forEach(input => {
        const key = input.dataset.key;
        if (input.type === 'checkbox') {
            unifiedStudyConfig[key] = input.checked;
        } else if (input.type === 'number') {
            unifiedStudyConfig[key] = input.step === '1' ? parseInt(input.value) : parseFloat(input.value);
        } else {
            unifiedStudyConfig[key] = input.value;
        }
    });
    
    // Tasks
    const taskInputs = document.querySelectorAll('.task-checkbox:checked');
    if (taskInputs.length > 0) {
        unifiedStudyConfig['TASKS'] = Array.from(taskInputs).map(cb => cb.value);
    } else if (schema.properties && schema.properties.TASKS) {
        unifiedStudyConfig['TASKS'] = [];
    }

    // Container info
    const containerType = document.querySelector('input[name="container_type"]:checked')?.value || 'docker';
    unifiedStudyConfig.container_type = containerType;
    
    unifiedStudyConfig.docker_image = document.getElementById('input-docker_image').value;
    unifiedStudyConfig.apptainer_image = document.getElementById('input-apptainer_image').value;
    unifiedStudyConfig.skip_validation = document.getElementById('skip_validation').checked;
    
    validationResult.innerHTML = '';
}

async function syncInternalToForm() {
    // Settings details
    for (const [key, val] of Object.entries(unifiedStudyConfig)) {
        const el = document.getElementById(`input-${key}`);
        if (el) {
            if (el.type === 'checkbox') el.checked = val;
            else el.value = val;
        }
        if (key === 'TASKS' && Array.isArray(val)) {
            await refreshTasks();
            val.forEach(t => {
                const cb = document.getElementById(`task-${t}`);
                if (cb) cb.checked = true;
            });
            await refreshSpaces();
        }
    }
    
    // Container info
    const type = unifiedStudyConfig.container_type || 'docker';
    const radio = document.getElementById(`type-${type}`);
    if (radio) {
        radio.checked = true;
        document.getElementById('docker-options').classList.toggle('d-none', type !== 'docker');
        document.getElementById('apptainer-options').classList.toggle('d-none', type !== 'apptainer');
        updateInternalState();
    }
    document.getElementById('input-docker_image').value = unifiedStudyConfig.docker_image || '';
    document.getElementById('input-apptainer_image').value = unifiedStudyConfig.apptainer_image || '';

    const skipVal = document.getElementById('skip_validation');
    if (skipVal) skipVal.checked = !!unifiedStudyConfig.skip_validation;
}
