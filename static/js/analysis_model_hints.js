(function () {
    function normalizeHintArray(value) {
        if (Array.isArray(value)) {
            return value.filter(item => typeof item === 'string' && item.trim()).map(item => item.trim());
        }
        if (typeof value === 'string' && value.trim()) {
            return [value.trim()];
        }
        return [];
    }

    function extractModelHintsClientSide(modelContent) {
        const input = modelContent && typeof modelContent === 'object' ? modelContent.Input || {} : {};
        const rawTasks = input && typeof input === 'object' ? input.task : [];
        const tasks = normalizeHintArray(rawTasks);

        const replaceValues = new Set();
        const contrastLevels = new Set();
        const contrastTerms = new Set();
        const fieldStatus = {
            model_tasks: tasks.length ? 'present' : 'absent',
            replace_values: 'absent',
            contrast_levels: 'absent'
        };

        const nodes = Array.isArray(modelContent?.Nodes) ? modelContent.Nodes : [];
        if (modelContent?.Nodes && !Array.isArray(modelContent.Nodes)) {
            fieldStatus.replace_values = 'invalid';
            fieldStatus.contrast_levels = 'invalid';
        }

        nodes.forEach(node => {
            if (!node || typeof node !== 'object') {
                fieldStatus.replace_values = 'invalid';
                fieldStatus.contrast_levels = 'invalid';
                return;
            }

            const transformations = node.Transformations;
            const instructions = Array.isArray(transformations?.Instructions) ? transformations.Instructions : [];
            if (transformations && typeof transformations !== 'object') {
                fieldStatus.replace_values = 'invalid';
            }

            instructions.forEach(instruction => {
                if (!instruction || typeof instruction !== 'object') {
                    fieldStatus.replace_values = 'invalid';
                    return;
                }
                if (instruction.Name !== 'Replace') return;
                const replacements = Array.isArray(instruction.Replace) ? instruction.Replace : [];
                if (instruction.Replace && !Array.isArray(instruction.Replace)) {
                    fieldStatus.replace_values = 'invalid';
                    return;
                }
                replacements.forEach(rep => {
                    if (!rep || typeof rep !== 'object') {
                        fieldStatus.replace_values = 'invalid';
                        return;
                    }
                    if (typeof rep.value === 'string' && rep.value.trim()) {
                        replaceValues.add(rep.value.trim());
                    }
                });
            });

            const contrasts = Array.isArray(node.Contrasts) ? node.Contrasts : [];
            if (node.Contrasts && !Array.isArray(node.Contrasts)) {
                fieldStatus.contrast_levels = 'invalid';
                return;
            }

            contrasts.forEach(contrast => {
                if (!contrast || typeof contrast !== 'object') {
                    fieldStatus.contrast_levels = 'invalid';
                    return;
                }
                const conditionList = Array.isArray(contrast.ConditionList) ? contrast.ConditionList : [];
                if (contrast.ConditionList && !Array.isArray(contrast.ConditionList)) {
                    fieldStatus.contrast_levels = 'invalid';
                    return;
                }
                conditionList.forEach(term => {
                    if (typeof term !== 'string' || !term.trim()) {
                        fieldStatus.contrast_levels = 'invalid';
                        return;
                    }
                    const cleanTerm = term.trim();
                    contrastTerms.add(cleanTerm);
                    const parts = cleanTerm.split('.');
                    contrastLevels.add(parts[parts.length - 1]);
                });
            });
        });

        if (replaceValues.size) fieldStatus.replace_values = 'present';
        if (contrastLevels.size) fieldStatus.contrast_levels = 'present';

        return {
            model_tasks: tasks,
            replace_values: Array.from(replaceValues).sort(),
            contrast_levels: Array.from(contrastLevels).sort(),
            contrast_terms: Array.from(contrastTerms).sort(),
            field_status: fieldStatus
        };
    }

    function chooseHintValues(serverValues, fallbackValues) {
        const primary = normalizeHintArray(serverValues);
        if (primary.length) return primary;
        return normalizeHintArray(fallbackValues);
    }

    function formatHintValues(values, status, emptyLabel) {
        if (values.length) return values.join(', ');
        if (status === 'invalid') return '<span class="text-warning">could not extract from model</span>';
        return `<span class="text-muted">${emptyLabel}</span>`;
    }

    function formatEventSample(values, status, missingColumnLabel) {
        const normalized = normalizeHintArray(values).slice(0, 10);
        if (normalized.length) return normalized.join(', ');
        if (status === 'missing-column') return `<span class="text-muted">${missingColumnLabel}</span>`;
        if (status === 'empty-column') return '<span class="text-muted">column present but no values sampled</span>';
        return '<span class="text-warning">sample not available</span>';
    }

    function renderModelHints(config, data, modelContent = null) {
        const panel = config?.panel;
        if (!panel) return;

        const warnings = data.warnings || [];
        const fallbackModel = extractModelHintsClientSide(modelContent || {});
        const serverModel = data.model || {};
        const serverStatus = serverModel.field_status || {};
        const fallbackStatus = fallbackModel.field_status || {};
        const model = {
            model_tasks: chooseHintValues(serverModel.model_tasks, fallbackModel.model_tasks),
            contrast_levels: chooseHintValues(serverModel.contrast_levels, fallbackModel.contrast_levels),
            replace_values: chooseHintValues(serverModel.replace_values, fallbackModel.replace_values),
            field_status: {
                model_tasks: normalizeHintArray(serverModel.model_tasks).length ? (serverStatus.model_tasks || 'present') : (normalizeHintArray(fallbackModel.model_tasks).length ? (fallbackStatus.model_tasks || 'present') : (serverStatus.model_tasks || fallbackStatus.model_tasks || 'absent')),
                contrast_levels: normalizeHintArray(serverModel.contrast_levels).length ? (serverStatus.contrast_levels || 'present') : (normalizeHintArray(fallbackModel.contrast_levels).length ? (fallbackStatus.contrast_levels || 'present') : (serverStatus.contrast_levels || fallbackStatus.contrast_levels || 'absent')),
                replace_values: normalizeHintArray(serverModel.replace_values).length ? (serverStatus.replace_values || 'present') : (normalizeHintArray(fallbackModel.replace_values).length ? (fallbackStatus.replace_values || 'present') : (serverStatus.replace_values || fallbackStatus.replace_values || 'absent'))
            }
        };
        const dataset = data.dataset || {};
        const events = dataset.events || {};
        const sampleValues = events.sample_values || {};
        const sampleStatus = events.sample_status || {};

        const warningHtml = warnings.length
            ? `<div class="alert alert-warning py-2 px-3 mb-2 x-small border-0 shadow-sm"><strong>Potential issues:</strong><br>${warnings.map(w => `- ${w}`).join('<br>')}</div>`
            : '<div class="alert alert-success py-2 px-3 mb-2 x-small border-0 shadow-sm">No obvious task/condition mismatches found.</div>';

        panel.innerHTML = `
            ${warningHtml}
            <div class="small text-muted">
                <div><strong>Detected BIDS tasks:</strong> ${normalizeHintArray(dataset.bids_tasks).join(', ') || '<span class="text-muted">none detected</span>'}</div>
                <div><strong>Model tasks:</strong> ${formatHintValues(model.model_tasks, model.field_status.model_tasks, 'not set in model')}</div>
                <div><strong>Model contrast levels:</strong> ${formatHintValues(model.contrast_levels, model.field_status.contrast_levels, 'not defined in model')}</div>
                <div><strong>Replace values in model:</strong> ${formatHintValues(model.replace_values, model.field_status.replace_values, 'not used in model')}</div>
                <div><strong>Event columns:</strong> ${normalizeHintArray(events.event_columns).join(', ') || '<span class="text-muted">none detected</span>'}</div>
                <div><strong>Sample trial_type:</strong> ${formatEventSample(sampleValues.trial_type, sampleStatus.trial_type, 'trial_type column not present')}</div>
                <div><strong>Sample condition:</strong> ${formatEventSample(sampleValues.condition, sampleStatus.condition, 'condition column not present')}</div>
            </div>
        `;
        panel.style.display = 'block';
    }

    async function refreshModelHints(config, explicitModelContent = null) {
        const panel = config?.panel;
        if (!panel) {
            return;
        }

        const modelPath = typeof config?.modelPath === 'function' ? config.modelPath() : config?.modelPath;
        const bidsDir = typeof config?.bidsDir === 'function' ? config.bidsDir() : config?.bidsDir;
        if (!modelPath) {
            panel.style.display = 'none';
            return;
        }

        const getModelContentFromPath = config?.getModelContentFromPath;
        const fetchImpl = config?.fetchImpl || window.fetch.bind(window);

        try {
            const modelContent = explicitModelContent || await getModelContentFromPath(modelPath);
            const response = await fetchImpl('/api/model_hints', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    model_path: modelPath,
                    model_content: modelContent,
                    bids_dir: bidsDir
                })
            });
            const data = await response.json();
            if (data.error) {
                panel.innerHTML = `<div class="alert alert-danger py-1 x-small mb-0">${data.error}</div>`;
                panel.style.display = 'block';
                return;
            }
            renderModelHints(config, data, modelContent);
        } catch (e) {
            panel.innerHTML = `<div class="alert alert-danger py-1 x-small mb-0">Hint generation failed: ${e.message}</div>`;
            panel.style.display = 'block';
        }
    }

    window.BidspmAnalysisModelHints = {
        chooseHintValues,
        extractModelHintsClientSide,
        formatEventSample,
        formatHintValues,
        normalizeHintArray,
        refreshModelHints,
        renderModelHints
    };
})();