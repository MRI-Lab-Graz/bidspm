// analysis_buttons.js
// Extracted from templates/analysis.html: toolbar/button event wiring (load config, save/start/stop runs, checks, bms list, participants).
// Classic script (shared globals); loaded before the inline bootstrap script in analysis.html.

// --- BUTTON EVENTS ---
document.getElementById('btn-validate').onclick = async () => {
    updateInternalState();
    validationResult.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Validating...';
    const res = await fetch('/validate_config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({content: unifiedStudyConfig})
    });
    const result = await res.json();
    if (result.valid) {
        validationResult.innerHTML = '<div class="alert alert-success py-1 x-small shadow-sm border-0"><i class="fas fa-check me-2"></i> Valid JSON configuration</div>';
    } else {
        validationResult.innerHTML = `<div class="alert alert-danger py-1 x-small shadow-sm border-0"><i class="fas fa-times me-2"></i> ${escapeHtml(result.error)}</div>`;
    }
    revealResult(validationResult);
};

document.getElementById('btn-check-paths').onclick = async () => {
    updateInternalState();
    const res = await fetch('/check_paths', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(unifiedStudyConfig)
    });
    const results = await res.json();
    pathAlerts.innerHTML = '';
    for (const [k, exists] of Object.entries(results)) {
        const div = document.createElement('div');
        div.className = `alert alert-${exists ? 'success' : 'danger'} py-1 x-small mb-1 shadow-sm border-0`;
        div.innerHTML = `<i class="fas fa-${exists ? 'check' : 'times'} me-1"></i> ${escapeHtml(k)}: ${exists ? 'Path found' : 'Path not found'}`;
        pathAlerts.appendChild(div);
    }
    revealResult(pathAlerts);
};

document.getElementById('btn-save-only').onclick = async () => {
    updateInternalState();

    const selectedContainer = document.querySelector('input[name="container_type"]:checked');
    if (selectedContainer) {
        unifiedStudyConfig.container_type = selectedContainer.value;
    }

    try {
        if (hasProject && currentProjectId) {
            await saveProjectConfig();
            validationResult.innerHTML = '<div class="alert alert-success py-1 x-small shadow-sm border-0"><i class="fas fa-check me-2"></i>Project configuration saved.</div>';
        } else {
            const folder = document.getElementById('config-folder')?.value;
            const filename = document.getElementById('study-filename')?.value;
            const studyPath = `${folder}${filename}`;

            await fetch('/save_settings', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({filepath: studyPath, content: unifiedStudyConfig})
            });

            validationResult.innerHTML = `<div class="alert alert-success py-1 x-small shadow-sm border-0"><i class="fas fa-check me-2"></i>Configuration saved to ${escapeHtml(studyPath)}</div>`;
        }
    } catch (err) {
        validationResult.innerHTML = `<div class="alert alert-danger py-1 x-small shadow-sm border-0"><i class="fas fa-times me-2"></i>Save failed: ${escapeHtml(err.message)}</div>`;
    }
    revealResult(validationResult);
};

document.getElementById('btn-save-start').onclick = async () => {
    updateInternalState();
    
    const selectedContainer = document.querySelector('input[name="container_type"]:checked');
    if (selectedContainer) {
        unifiedStudyConfig.container_type = selectedContainer.value;
    }

    const coverageDecision = await runStatsCoverageGate();
    if (!coverageDecision.allow) return;
    
    const data = getFullFormData();
    if (selectedParticipants) {
        data.subjects_override = Array.from(selectedParticipants);
    } else if (coverageDecision.subjectsOverride.length > 0) {
        data.subjects_override = coverageDecision.subjectsOverride;
    }

    if (hasProject && currentProjectId) {
        // Save to project
        await saveProjectConfig();
        
        const runPayload = {
            ...data,
            project_id: currentProjectId,
            settings: null
        };
        delete runPayload.container;
        startExecution(runPayload);
    } else {
        // Legacy mode: save to file
        const folder = data.config_folder;
        const study_path = folder + data.study_filename;
        
        await fetch('/save_settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({filepath: study_path, content: unifiedStudyConfig})
        });
        
        const runPayload = {
            ...data,
            settings: study_path
        };
        delete runPayload.container;
        
        await fetch('/save_config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({config: runPayload, folder: folder, filename: "study_run_meta.json"})
        });
        
        startExecution(runPayload);
    }
};

document.getElementById('btn-run-cached').onclick = () => {
    (async () => {
        updateInternalState();
        const coverageDecision = await runStatsCoverageGate();
        if (!coverageDecision.allow) return;

        const data = getFullFormData();
        if (selectedParticipants) {
            data.subjects_override = Array.from(selectedParticipants);
        } else if (coverageDecision.subjectsOverride.length > 0) {
            data.subjects_override = coverageDecision.subjectsOverride;
        }

        if (hasProject && currentProjectId) {
            const runPayload = {
                ...data,
                project_id: currentProjectId
            };
            delete runPayload.container;
            startExecution(runPayload);
        } else {
            const folder = data.config_folder;
            const study_path = folder + data.study_filename;
            const runPayload = {
                ...data,
                settings: study_path
            };
            delete runPayload.container;
            startExecution(runPayload);
        }
    })();
};

document.getElementById('btn-stop').onclick = async () => {
    const res = await fetch('/stop', {method: 'POST'});
    const result = await res.json();
    if (result.status === 'stopping') {
        terminal.innerText += '\n--- STOP REQUESTED ---\n';
        execStatus.innerText = 'STOPPING';
        execStatus.className = 'badge bg-warning text-dark';
    }
};

document.getElementById('btn-load-config')?.addEventListener('click', async () => {
    if (hasProject) {
        // Browse for config to import into project
        alert('Use the Projects page to import configurations into projects.');
        return;
    }
    
    const folder = document.getElementById('config-folder').value;
    const res = await fetch(`/configs?folder=${folder}`);
    const files = await res.json();
    const list = document.getElementById('config-list');
    list.innerHTML = '';
    if (files.length === 0) {
        list.innerHTML = '<div class="p-4 text-muted text-center italic">No configuration files found in this folder.</div>';
    } else {
        files.forEach(f => {
            const btn = document.createElement('button');
            btn.className = 'list-group-item list-group-item-action small py-2 d-flex justify-content-between align-items-center';
            btn.innerHTML = `<span><i class="fas fa-file-invoice me-2 text-primary"></i> ${escapeHtml(f)}</span> <i class="fas fa-chevron-right text-muted x-small"></i>`;
            btn.onclick = async () => {
                const r = await fetch(`/load_config?folder=${folder}&filename=${f}`);
                const data = await r.json();
                
                if (data.study_content) {
                    await setFullFormData(data);
                } else {
                    unifiedStudyConfig = data;
                    document.getElementById('study-filename').value = f;
                    syncInternalToForm();
                }
                bootstrap.Modal.getInstance(document.getElementById('loadConfigModal')).hide();
            };
            list.appendChild(btn);
        });
    }
    new bootstrap.Modal(document.getElementById('loadConfigModal')).show();
});
