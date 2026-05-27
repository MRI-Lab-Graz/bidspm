(function () {
    function isReadonlyModelPath(path) {
        return READONLY_MODEL_PATHS.some(rx => rx.test(path));
    }

    function formatModelSectionLabel(key) {
        return String(key || '')
            .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
            .replace(/[_-]+/g, ' ')
            .replace(/\s+/g, ' ')
            .trim()
            .replace(/^./, char => char.toUpperCase());
    }

    function isFilledModelValue(value) {
        if (Array.isArray(value)) return value.some(item => isFilledModelValue(item));
        if (value && typeof value === 'object') return Object.values(value).some(item => isFilledModelValue(item));
        if (typeof value === 'string') return value.trim() !== '';
        return value !== null && value !== undefined;
    }

    function getCompletionDotClass(filled, total) {
        if (!total || filled <= 0) return 'empty';
        if (filled >= total) return 'full';
        return 'partial';
    }

    function getModelPillTone(filled, total) {
        if (!total || filled <= 0) return 'neutral';
        const pct = Math.round((filled / total) * 100);
        if (pct >= 100) return 'success';
        if (pct >= 45) return 'warning';
        return 'neutral';
    }

    function appendModelMetaPill(container, text, tone = 'neutral') {
        const pill = document.createElement('span');
        pill.className = `model-meta-pill model-meta-pill-${tone}`;
        pill.textContent = text;
        container.appendChild(pill);
    }

    function getDirectFieldCompletion(value) {
        if (Array.isArray(value)) {
            return { total: 1, filled: value.length > 0 ? 1 : 0 };
        }
        if (value && typeof value === 'object') {
            const entries = Object.entries(value);
            if (!entries.length) {
                return { total: 1, filled: 0 };
            }
            return {
                total: entries.length,
                filled: entries.filter(([, child]) => isFilledModelValue(child)).length
            };
        }
        return { total: 1, filled: isFilledModelValue(value) ? 1 : 0 };
    }

    function createModelStats({ filled = 0, total = 0, badges = [], subtitle = '' } = {}) {
        return {
            filled,
            total,
            badges,
            subtitle,
            dotClass: getCompletionDotClass(filled, total)
        };
    }

    function getOverviewSectionValue(model) {
        const primitiveKeys = Object.entries(model || {})
            .filter(([key, value]) => key !== 'Input' && key !== 'Nodes' && (value === null || typeof value !== 'object'))
            .map(([key]) => key);
        const keys = Array.from(new Set(['Name', 'BIDSModelVersion', 'Description', ...primitiveKeys]));
        return Object.fromEntries(keys.map(key => [key, model?.[key] ?? '']));
    }

    function getOverviewSectionStats(model) {
        const overviewValue = getOverviewSectionValue(model);
        const keys = Object.keys(overviewValue);
        const filled = keys.filter(key => isFilledModelValue(overviewValue[key])).length;
        const requiredKeys = ['Name', 'BIDSModelVersion'];
        const requiredFilled = requiredKeys.filter(key => isFilledModelValue(model?.[key])).length;
        const topLevelChecks = getTopLevelSchemaChecks(model);
        const graphReady = topLevelChecks.nodesArray && topLevelChecks.nodeNameUnique && topLevelChecks.edgeRefsValid;

        return createModelStats({
            filled,
            total: keys.length,
            subtitle: 'Name, version and metadata',
            badges: [
                { text: `Required ${requiredFilled}/${requiredKeys.length}`, tone: requiredFilled === requiredKeys.length ? 'success' : 'warning' },
                { text: `Top-level ${topLevelChecks.passedRequired}/${topLevelChecks.totalRequired}`, tone: topLevelChecks.passedRequired === topLevelChecks.totalRequired ? 'success' : 'warning' },
                { text: graphReady ? 'Graph consistent' : 'Graph needs review', tone: graphReady ? 'neutral' : 'warning' },
                { text: `Fields ${filled}/${keys.length}`, tone: getModelPillTone(filled, keys.length) }
            ]
        });
    }

    function getInputSectionStats(inputValue) {
        const selectedTasks = Array.isArray(inputValue?.task) ? inputValue.task.filter(Boolean).length : 0;
        const extraInput = inputValue && typeof inputValue === 'object'
            ? Object.fromEntries(Object.entries(inputValue).filter(([key]) => key !== 'task'))
            : {};
        const extraStats = getDirectFieldCompletion(extraInput);
        const total = 1 + (Object.keys(extraInput).length ? extraStats.total : 0);
        const filled = (selectedTasks > 0 ? 1 : 0) + (Object.keys(extraInput).length ? extraStats.filled : 0);

        return createModelStats({
            filled,
            total,
            subtitle: 'Tasks and input filters',
            badges: [
                { text: `Required ${selectedTasks > 0 ? 1 : 0}/1`, tone: selectedTasks > 0 ? 'success' : 'warning' },
                { text: `Selected ${selectedTasks}`, tone: selectedTasks > 0 ? 'success' : 'neutral' }
            ]
        });
    }

    function getNodesSectionStats(nodes) {
        const list = Array.isArray(nodes) ? nodes : [];
        const readyNodes = list.filter(node => getNodeSchemaIssues(node).length === 0).length;
        const total = list.length > 0 ? list.length : 1;
        const filled = readyNodes;

        return createModelStats({
            filled,
            total,
            subtitle: list.length > 0
                ? 'Nodes, transforms, design and contrasts'
                : 'No nodes yet. Use + Add Node to create the first node',
            badges: [
                { text: `Required ${list.length > 0 ? 1 : 0}/1`, tone: list.length > 0 ? 'success' : 'warning' },
                { text: `Ready ${readyNodes}/${list.length || 0}`, tone: list.length > 0 ? getModelPillTone(readyNodes, list.length) : 'neutral' },
                { text: `Nodes ${list.length}`, tone: 'neutral' }
            ]
        });
    }

    function getEdgesSectionStats(edges) {
        const list = Array.isArray(edges) ? edges : [];
        const nodeNames = Array.isArray(modelEditorDraft?.Nodes)
            ? modelEditorDraft.Nodes.map(node => String(node?.Name || '').trim()).filter(Boolean)
            : [];
        const knownFilterKeys = getKnownEdgeFilterMetadataKeys();
        const readyEdges = list.filter(edge => getEdgeSchemaIssues(edge, nodeNames, knownFilterKeys).length === 0).length;
        const withFilter = list.filter(edge => edge?.Filter && typeof edge.Filter === 'object' && !Array.isArray(edge.Filter)).length;
        const withUnknownFilterKeys = list.filter(edge => getEdgeSchemaAdvisories(edge, nodeNames, knownFilterKeys).length > 0).length;
        const total = list.length > 0 ? list.length : 1;

        return createModelStats({
            filled: readyEdges,
            total,
            subtitle: 'Source to destination node links',
            badges: [
                { text: `Edges ${list.length}`, tone: list.length > 0 ? 'success' : 'neutral' },
                { text: `Ready ${readyEdges}/${list.length || 0}`, tone: list.length > 0 ? getModelPillTone(readyEdges, list.length) : 'neutral' },
                { text: `With filter ${withFilter}`, tone: 'neutral' },
                { text: withUnknownFilterKeys ? `Unknown filter keys ${withUnknownFilterKeys}` : 'Known filter keys', tone: withUnknownFilterKeys ? 'warning' : 'neutral' }
            ]
        });
    }

    function getGenericSectionStats(value, label) {
        const stats = getDirectFieldCompletion(value);
        const isArray = Array.isArray(value);
        const count = isArray ? value.length : Object.keys(value || {}).length;

        return createModelStats({
            filled: stats.filled,
            total: stats.total,
            subtitle: `${formatModelSectionLabel(label)} section`,
            badges: [
                { text: isArray ? `Items ${count}` : `Fields ${stats.filled}/${stats.total}`, tone: getModelPillTone(stats.filled, stats.total) }
            ]
        });
    }

    function getModelEditorSections(model) {
        const sections = [
            {
                id: '__section_overview',
                label: 'Model Overview',
                path: '',
                statePath: '__section_overview',
                value: getOverviewSectionValue(model),
                kind: 'overview',
                icon: 'fa-file-lines',
                stats: getOverviewSectionStats(model)
            },
            {
                id: 'Input',
                label: 'Input',
                path: 'Input',
                statePath: 'Input',
                value: model?.Input ?? {},
                kind: 'input',
                icon: 'fa-sliders',
                stats: getInputSectionStats(model?.Input)
            },
            {
                id: 'Nodes',
                label: 'Nodes',
                path: 'Nodes',
                statePath: 'Nodes',
                value: Array.isArray(model?.Nodes) ? model.Nodes : [],
                kind: 'nodes',
                icon: 'fa-diagram-project',
                stats: getNodesSectionStats(model?.Nodes)
            },
            {
                id: 'Edges',
                label: 'Edges',
                path: 'Edges',
                statePath: 'Edges',
                value: Array.isArray(model?.Edges) ? model.Edges : [],
                kind: 'array',
                icon: 'fa-share-nodes',
                stats: getEdgesSectionStats(model?.Edges)
            }
        ];

        Object.entries(model || {}).forEach(([key, value]) => {
            if (key === 'Input' || key === 'Nodes' || key === 'Edges' || value === null || typeof value !== 'object') {
                return;
            }
            sections.push({
                id: key,
                label: formatModelSectionLabel(key),
                path: key,
                statePath: key,
                value,
                kind: Array.isArray(value) ? 'array' : 'object',
                icon: Array.isArray(value) ? 'fa-layer-group' : 'fa-folder-tree',
                stats: getGenericSectionStats(value, key)
            });
        });

        return sections;
    }

    function computeModelEditorSummary(model) {
        const sections = getModelEditorSections(model);
        const totals = sections.reduce((acc, section) => {
            acc.filled += section.stats.filled;
            acc.total += section.stats.total;
            return acc;
        }, { filled: 0, total: 0 });

        return {
            score: totals.total > 0 ? Math.round((totals.filled / totals.total) * 100) : 0,
            filled: totals.filled,
            total: totals.total,
            sections
        };
    }

    function renderModelEditorSummary(summary) {
        const summaryPanel = document.getElementById('model-editor-summary');
        const progressBar = document.getElementById('model-editor-progress-bar');
        const score = document.getElementById('model-editor-score');
        const ring = document.getElementById('model-editor-score-ring');
        const ringLabel = document.getElementById('model-editor-score-ring-label');
        const sectionSummary = document.getElementById('model-editor-section-summary');

        if (!summaryPanel || !progressBar || !score || !ring || !ringLabel || !sectionSummary) {
            return;
        }

        if (!summary) {
            summaryPanel.classList.add('d-none');
            sectionSummary.innerHTML = '';
            return;
        }

        summaryPanel.classList.remove('d-none');
        progressBar.style.width = `${summary.score}%`;
        score.textContent = `${summary.score}%`;
        ring.style.setProperty('--model-progress', String(summary.score));
        ringLabel.textContent = `${summary.score}%`;

        sectionSummary.innerHTML = '';
        summary.sections.forEach(section => {
            const row = document.createElement('div');
            row.className = 'model-section-summary-row';

            const label = document.createElement('span');
            label.className = 'section-label';
            label.textContent = section.label;

            const dot = document.createElement('span');
            dot.className = `completeness-dot ${section.stats.dotClass}`;
            dot.title = `${section.stats.filled}/${section.stats.total}`;

            const pills = document.createElement('div');
            pills.className = 'model-meta-pills';
            section.stats.badges.forEach(badge => appendModelMetaPill(pills, badge.text, badge.tone));

            row.appendChild(label);
            row.appendChild(dot);
            row.appendChild(pills);
            sectionSummary.appendChild(row);
        });
    }

    function getModelSchemaIssues(modelValue) {
        const issues = [];
        if (!modelValue || typeof modelValue !== 'object' || Array.isArray(modelValue)) {
            issues.push('Model must be an object.');
            return issues;
        }

        const modelType = typeof modelValue.Type === 'string' ? modelValue.Type.trim() : '';
        if (!modelType) {
            issues.push('Type is required.');
        } else if (!['glm', 'meta'].includes(modelType)) {
            issues.push('Type must be glm or meta.');
        }

        if (!Array.isArray(modelValue.X)) {
            issues.push('X is required and must be an array.');
        } else {
            const invalidEntry = modelValue.X.find(item => !(typeof item === 'string' || item === 1));
            if (invalidEntry !== undefined) issues.push('X entries must be strings or integer 1.');
        }

        return issues;
    }

    function createModelSchemaHint(modelValue) {
        const hint = document.createElement('div');
        const issues = getModelSchemaIssues(modelValue);
        const optionalFields = 'Formula, HRF, Options, Software';

        hint.className = issues.length
            ? 'small border rounded p-2 mb-2 bg-warning-subtle text-warning-emphasis'
            : 'small border rounded p-2 mb-2 bg-light-subtle text-muted';

        const summary = document.createElement('div');
        summary.className = 'fw-semibold';
        summary.textContent = issues.length
            ? 'Model schema: missing or invalid required fields.'
            : 'Model schema: required Type and X are present.';
        hint.appendChild(summary);

        if (issues.length) {
            const detail = document.createElement('div');
            detail.textContent = issues.join(' ');
            hint.appendChild(detail);
        }

        const optional = document.createElement('div');
        optional.className = 'mt-1';
        optional.textContent = `Optional official fields: ${optionalFields}.`;
        hint.appendChild(optional);

        return hint;
    }

    function getNodeSchemaChecks(nodeValue) {
        const levelValue = typeof nodeValue?.Level === 'string' ? nodeValue.Level.trim() : '';
        const levelValid = ['Run', 'Session', 'Subject', 'Dataset'].includes(levelValue);
        const nameValid = typeof nodeValue?.Name === 'string' && nodeValue.Name.trim() !== '';
        const groupByValid = Array.isArray(nodeValue?.GroupBy)
            && nodeValue.GroupBy.length > 0
            && nodeValue.GroupBy.every(entry => typeof entry === 'string' && entry.trim() !== '');
        const modelType = typeof nodeValue?.Model?.Type === 'string' ? nodeValue.Model.Type.trim() : '';
        const modelTypeValid = ['glm', 'meta'].includes(modelType);
        const modelXValid = Array.isArray(nodeValue?.Model?.X);

        const checks = [levelValid, nameValid, groupByValid, modelTypeValid, modelXValid];
        return {
            levelValid,
            nameValid,
            groupByValid,
            modelTypeValid,
            modelXValid,
            passed: checks.filter(Boolean).length,
            total: checks.length
        };
    }

    function getNodeSchemaIssues(nodeValue) {
        const checks = getNodeSchemaChecks(nodeValue);
        const issues = [];
        if (!checks.levelValid) issues.push('Level is required and must be Run, Session, Subject, or Dataset.');
        if (!checks.nameValid) issues.push('Name is required.');
        if (!checks.groupByValid) issues.push('GroupBy is required and must be a non-empty string array.');
        if (!checks.modelTypeValid) issues.push('Model.Type is required and must be glm or meta.');
        if (!checks.modelXValid) issues.push('Model.X is required and must be an array.');
        return issues;
    }

    function createNodeSchemaHint(nodeValue) {
        const hint = document.createElement('div');
        const issues = getNodeSchemaIssues(nodeValue);

        hint.className = issues.length
            ? 'small border rounded p-2 mb-2 bg-warning-subtle text-warning-emphasis'
            : 'small border rounded p-2 mb-2 bg-light-subtle text-muted';

        const summary = document.createElement('div');
        summary.className = 'fw-semibold';
        summary.textContent = issues.length
            ? 'Node schema: missing or invalid required fields.'
            : 'Node schema: required Level, Name, GroupBy and Model(Type,X) are present.';
        hint.appendChild(summary);

        if (issues.length) {
            const detail = document.createElement('div');
            detail.textContent = issues.join(' ');
            hint.appendChild(detail);
        }

        return hint;
    }

    function getHrfSchemaChecks(hrfValue, modelX = []) {
        const modelValid = typeof hrfValue?.Model === 'string' && hrfValue.Model.trim() !== '';
        const variablesArray = Array.isArray(hrfValue?.Variables);
        const variablesEntriesValid = variablesArray
            && hrfValue.Variables.every(item => typeof item === 'string' && item.trim() !== '');
        const variablesInX = variablesEntriesValid
            ? hrfValue.Variables.every(item => modelX.includes(item))
            : false;

        return {
            modelValid,
            variablesArray,
            variablesEntriesValid,
            variablesInX,
            passedRequired: (modelValid ? 1 : 0) + (variablesArray && variablesEntriesValid ? 1 : 0),
            totalRequired: 2,
            variableCount: variablesArray ? hrfValue.Variables.length : 0
        };
    }

    function getHrfSchemaIssues(hrfValue, modelX = []) {
        const checks = getHrfSchemaChecks(hrfValue, modelX);
        const issues = [];
        if (!checks.modelValid) issues.push('Model is required and must be a non-empty string.');
        if (!checks.variablesArray) issues.push('Variables is required and must be an array.');
        else if (!checks.variablesEntriesValid) issues.push('Variables entries must be non-empty strings.');
        if (checks.variablesEntriesValid && !checks.variablesInX) issues.push('Each HRF variable should also appear in Model.X.');
        return issues;
    }

    function createHrfSchemaHint(hrfValue, modelX = []) {
        const hint = document.createElement('div');
        const issues = getHrfSchemaIssues(hrfValue, modelX);

        hint.className = issues.length
            ? 'small border rounded p-2 mb-2 bg-warning-subtle text-warning-emphasis'
            : 'small border rounded p-2 mb-2 bg-light-subtle text-muted';

        const summary = document.createElement('div');
        summary.className = 'fw-semibold';
        summary.textContent = issues.length
            ? 'HRF schema: missing or invalid required fields.'
            : 'HRF schema: required Variables and Model are present.';
        hint.appendChild(summary);

        if (issues.length) {
            const detail = document.createElement('div');
            detail.textContent = issues.join(' ');
            hint.appendChild(detail);
        }

        const optional = document.createElement('div');
        optional.className = 'mt-1';
        optional.textContent = 'Optional official field: Parameters (software-specific; fir may require fir_delays).';
        hint.appendChild(optional);

        return hint;
    }

    function getOptionsSchemaChecks(optionsValue) {
        const knownKeys = ['Description', 'HighPassFilterCutoffHz', 'LowPassFilterCutoffHz', 'ReplaceVariables', 'Mask', 'Aggregate'];
        const keys = optionsValue && typeof optionsValue === 'object' && !Array.isArray(optionsValue)
            ? Object.keys(optionsValue)
            : [];

        const unknownKeys = keys.filter(key => !knownKeys.includes(key));
        const highPass = optionsValue?.HighPassFilterCutoffHz;
        const lowPass = optionsValue?.LowPassFilterCutoffHz;
        const replaceVariables = optionsValue?.ReplaceVariables;
        const mask = optionsValue?.Mask;
        const aggregate = optionsValue?.Aggregate;

        const highPassValid = highPass === undefined || highPass === null || typeof highPass === 'number';
        const lowPassValid = lowPass === undefined || lowPass === null || typeof lowPass === 'number';
        const replaceVariablesValid = replaceVariables === undefined || replaceVariables === null || (typeof replaceVariables === 'object' && !Array.isArray(replaceVariables));
        const maskValid = mask === undefined || mask === null || (
            typeof mask === 'object' && !Array.isArray(mask)
            && Object.values(mask).every(value => Array.isArray(value))
        );
        const aggregateValid = aggregate === undefined || aggregate === null || ['none', 'mean', 'pca'].includes(String(aggregate));

        return {
            unknownKeys,
            highPassValid,
            lowPassValid,
            replaceVariablesValid,
            maskValid,
            aggregateValid,
            providedCount: keys.filter(key => optionsValue[key] !== null && optionsValue[key] !== undefined).length
        };
    }

    function getOptionsSchemaIssues(optionsValue) {
        const checks = getOptionsSchemaChecks(optionsValue);
        const issues = [];
        if (checks.unknownKeys.length) issues.push(`Unknown Options field(s): ${checks.unknownKeys.join(', ')}.`);
        if (!checks.highPassValid) issues.push('HighPassFilterCutoffHz must be a number or null.');
        if (!checks.lowPassValid) issues.push('LowPassFilterCutoffHz must be a number or null.');
        if (!checks.replaceVariablesValid) issues.push('ReplaceVariables must be an object or null.');
        if (!checks.maskValid) issues.push('Mask must be an object of array values or null.');
        if (!checks.aggregateValid) issues.push('Aggregate must be one of: none, mean, pca, or null.');
        return issues;
    }

    function createOptionsSchemaHint(optionsValue) {
        const hint = document.createElement('div');
        const issues = getOptionsSchemaIssues(optionsValue);

        hint.className = issues.length
            ? 'small border rounded p-2 mb-2 bg-warning-subtle text-warning-emphasis'
            : 'small border rounded p-2 mb-2 bg-light-subtle text-muted';

        const summary = document.createElement('div');
        summary.className = 'fw-semibold';
        summary.textContent = issues.length
            ? 'Options schema: invalid values or unsupported keys detected.'
            : 'Options schema: all official fields are optional.';
        hint.appendChild(summary);

        if (issues.length) {
            const detail = document.createElement('div');
            detail.textContent = issues.join(' ');
            hint.appendChild(detail);
        }

        const fields = document.createElement('div');
        fields.className = 'mt-1';
        fields.textContent = 'Official fields: HighPassFilterCutoffHz, LowPassFilterCutoffHz, ReplaceVariables, Mask, Aggregate.';
        hint.appendChild(fields);

        return hint;
    }

    function getContrastSchemaChecks(contrastValue) {
        const nameValid = typeof contrastValue?.Name === 'string' && contrastValue.Name.trim() !== '';

        const testValue = typeof contrastValue?.Test === 'string' ? contrastValue.Test.trim() : '';
        const testValid = ['pass', 't', 'F'].includes(testValue);

        const conditionListArray = Array.isArray(contrastValue?.ConditionList);
        const conditionEntriesValid = conditionListArray && contrastValue.ConditionList.every(item => typeof item === 'string' || item === 1);
        const conditionCount = conditionListArray ? contrastValue.ConditionList.length : 0;

        const weightsArray = Array.isArray(contrastValue?.Weights);
        const matrixWeights = weightsArray && contrastValue.Weights.some(item => Array.isArray(item));
        const weightEntriesValid = weightsArray && (matrixWeights
            ? contrastValue.Weights.every(row => Array.isArray(row) && row.every(entry => typeof entry === 'number' || typeof entry === 'string'))
            : contrastValue.Weights.every(entry => typeof entry === 'number' || typeof entry === 'string'));

        const weightShapeValid = weightsArray && conditionListArray && conditionCount > 0 && (matrixWeights
            ? contrastValue.Weights.every(row => Array.isArray(row) && row.length === conditionCount)
            : contrastValue.Weights.length === conditionCount);

        const conditionListValid = conditionListArray && conditionEntriesValid && conditionCount > 0;
        const weightsValid = weightsArray && weightEntriesValid && weightShapeValid;

        return {
            nameValid,
            conditionListValid,
            weightsValid,
            testValid,
            conditionCount,
            weightCount: weightsArray ? contrastValue.Weights.length : 0,
            matrixWeights,
            passedRequired: (nameValid ? 1 : 0) + (conditionListValid ? 1 : 0) + (weightsValid ? 1 : 0) + (testValid ? 1 : 0),
            totalRequired: 4
        };
    }

    function getContrastSchemaIssues(contrastValue) {
        const checks = getContrastSchemaChecks(contrastValue);
        const issues = [];
        if (!checks.nameValid) issues.push('Name is required.');
        if (!checks.conditionListValid) issues.push('ConditionList is required, non-empty, and entries must be strings or integer 1.');
        if (!checks.weightsValid) issues.push('Weights is required and must align with ConditionList length (vector or matrix rows).');
        if (!checks.testValid) issues.push('Test is required and must be one of: pass, t, F.');
        return issues;
    }

    function createContrastSchemaHint(contrastValue) {
        const hint = document.createElement('div');
        const issues = getContrastSchemaIssues(contrastValue);

        hint.className = issues.length
            ? 'small border rounded p-2 mb-2 bg-warning-subtle text-warning-emphasis'
            : 'small border rounded p-2 mb-2 bg-light-subtle text-muted';

        const summary = document.createElement('div');
        summary.className = 'fw-semibold';
        summary.textContent = issues.length
            ? 'Contrast schema: missing or invalid required fields.'
            : 'Contrast schema: required Name, ConditionList, Weights and Test are present.';
        hint.appendChild(summary);

        if (issues.length) {
            const detail = document.createElement('div');
            detail.textContent = issues.join(' ');
            hint.appendChild(detail);
        }

        const optional = document.createElement('div');
        optional.className = 'mt-1';
        optional.textContent = 'Optional official field: Description.';
        hint.appendChild(optional);

        return hint;
    }

    function getDummyContrastsSchemaChecks(dummyValue, modelX = []) {
        const knownKeys = ['Contrasts', 'Test'];
        const keys = dummyValue && typeof dummyValue === 'object' && !Array.isArray(dummyValue)
            ? Object.keys(dummyValue)
            : [];
        const unknownKeys = keys.filter(key => !knownKeys.includes(key));

        const testValue = typeof dummyValue?.Test === 'string' ? dummyValue.Test.trim() : '';
        const testValid = ['pass', 't', 'F'].includes(testValue);

        const contrastsValue = dummyValue?.Contrasts;
        const contrastsArray = contrastsValue === undefined || contrastsValue === null || Array.isArray(contrastsValue);
        const contrastsEntriesValid = !Array.isArray(contrastsValue)
            ? true
            : contrastsValue.every(item => typeof item === 'string' || item === 1);

        const normalizedModelX = Array.isArray(modelX)
            ? modelX.map(item => String(item === 1 ? '1' : item || '').trim()).filter(Boolean)
            : [];
        const modelXSet = new Set(normalizedModelX);
        const subsetCheckApplicable = Array.isArray(contrastsValue) && contrastsEntriesValid && modelXSet.size > 0;
        const contrastsSubsetValid = !subsetCheckApplicable || contrastsValue.every(item => {
            const token = item === 1 ? '1' : String(item || '').trim();
            return modelXSet.has(token);
        });

        return {
            unknownKeys,
            testValid,
            testValue,
            contrastsArray,
            contrastsEntriesValid,
            contrastsSubsetValid,
            subsetCheckApplicable,
            contrastsCount: Array.isArray(contrastsValue) ? contrastsValue.length : 0,
            passedRequired: testValid ? 1 : 0,
            totalRequired: 1
        };
    }

    function getDummyContrastsSchemaIssues(dummyValue, modelX = []) {
        const checks = getDummyContrastsSchemaChecks(dummyValue, modelX);
        const issues = [];
        if (checks.unknownKeys.length) issues.push(`Unknown DummyContrasts field(s): ${checks.unknownKeys.join(', ')}.`);
        if (!checks.testValid) issues.push('Test is required and must be one of: pass, t, F.');
        if (!checks.contrastsArray) issues.push('Contrasts must be an array or null when provided.');
        if (!checks.contrastsEntriesValid) issues.push('Contrasts entries must be strings or integer 1.');
        if (checks.subsetCheckApplicable && !checks.contrastsSubsetValid) issues.push('Contrasts should be a strict subset of Model.X.');
        return issues;
    }

    function createDummyContrastsSchemaHint(dummyValue, modelX = []) {
        const hint = document.createElement('div');
        const issues = getDummyContrastsSchemaIssues(dummyValue, modelX);

        hint.className = issues.length
            ? 'small border rounded p-2 mb-2 bg-warning-subtle text-warning-emphasis'
            : 'small border rounded p-2 mb-2 bg-light-subtle text-muted';

        const summary = document.createElement('div');
        summary.className = 'fw-semibold';
        summary.textContent = issues.length
            ? 'DummyContrasts schema: missing or invalid fields.'
            : 'DummyContrasts schema: required Test is present; optional Contrasts is valid.';
        hint.appendChild(summary);

        if (issues.length) {
            const detail = document.createElement('div');
            detail.textContent = issues.join(' ');
            hint.appendChild(detail);
        }

        const optional = document.createElement('div');
        optional.className = 'mt-1';
        optional.textContent = 'If Contrasts is omitted, dummy contrasts are generated for all Model.X variables. F contrasts are terminal and not passed to downstream nodes.';
        hint.appendChild(optional);

        return hint;
    }

    function getKnownEdgeFilterMetadataKeys() {
        const participantInfo = getModelEditorParticipantsInfo();
        const participantColumns = [
            ...normalizeStringArray(participantInfo?.categorical_columns),
            ...normalizeStringArray(participantInfo?.numeric_columns)
        ];
        const nodeGroupByKeys = Array.isArray(modelEditorDraft?.Nodes)
            ? modelEditorDraft.Nodes.flatMap(node => normalizeStringArray(node?.GroupBy))
            : [];
        return Array.from(new Set([
            'contrast', 'task', 'run', 'session', 'subject', 'space', 'datatype', 'suffix', 'desc', 'extension',
            ...normalizeStringArray(modelEditorGroupByOptions),
            ...participantColumns,
            ...nodeGroupByKeys
        ]));
    }

    function getEdgeSchemaChecks(edgeValue, nodeNames = [], knownFilterKeys = []) {
        const knownKeys = ['Source', 'Destination', 'Filter'];
        const keys = edgeValue && typeof edgeValue === 'object' && !Array.isArray(edgeValue)
            ? Object.keys(edgeValue)
            : [];
        const unknownKeys = keys.filter(key => !knownKeys.includes(key));

        const sourceValue = typeof edgeValue?.Source === 'string' ? edgeValue.Source.trim() : '';
        const destinationValue = typeof edgeValue?.Destination === 'string' ? edgeValue.Destination.trim() : '';
        const sourceValid = sourceValue !== '';
        const destinationValid = destinationValue !== '';

        const nodeNameSet = new Set(
            Array.isArray(nodeNames)
                ? nodeNames.map(name => String(name || '').trim()).filter(Boolean)
                : []
        );
        const sourceKnown = !sourceValid ? false : (nodeNameSet.size === 0 || nodeNameSet.has(sourceValue));
        const destinationKnown = !destinationValid ? false : (nodeNameSet.size === 0 || nodeNameSet.has(destinationValue));

        const filterValue = edgeValue?.Filter;
        const filterProvided = filterValue !== undefined && filterValue !== null;
        const filterValid = !filterProvided || (
            typeof filterValue === 'object'
            && !Array.isArray(filterValue)
            && Object.values(filterValue).every(value => Array.isArray(value))
        );
        const filterKeys = filterProvided && typeof filterValue === 'object' && !Array.isArray(filterValue)
            ? Object.keys(filterValue).filter(Boolean)
            : [];
        const knownFilterKeySet = new Set(
            Array.isArray(knownFilterKeys)
                ? knownFilterKeys.map(key => String(key || '').trim()).filter(Boolean)
                : []
        );
        const unknownFilterKeys = knownFilterKeySet.size
            ? filterKeys.filter(key => !knownFilterKeySet.has(String(key || '').trim()))
            : [];
        const filterKeyCount = filterProvided && typeof filterValue === 'object' && !Array.isArray(filterValue)
            ? Object.keys(filterValue).length
            : 0;

        return {
            unknownKeys,
            sourceValue,
            destinationValue,
            sourceValid,
            destinationValid,
            sourceKnown,
            destinationKnown,
            filterProvided,
            filterValid,
            filterKeys,
            unknownFilterKeys,
            filterKeyCount,
            passedRequired: (sourceValid ? 1 : 0) + (destinationValid ? 1 : 0),
            totalRequired: 2,
            nodeNameCount: nodeNameSet.size
        };
    }

    function getEdgeSchemaIssues(edgeValue, nodeNames = [], knownFilterKeys = []) {
        const checks = getEdgeSchemaChecks(edgeValue, nodeNames, knownFilterKeys);
        const issues = [];
        if (checks.unknownKeys.length) issues.push(`Unknown Edge field(s): ${checks.unknownKeys.join(', ')}.`);
        if (!checks.sourceValid) issues.push('Source is required and must be a non-empty string.');
        if (!checks.destinationValid) issues.push('Destination is required and must be a non-empty string.');
        if (checks.nodeNameCount > 0 && checks.sourceValid && !checks.sourceKnown) issues.push('Source should match an existing Node.Name.');
        if (checks.nodeNameCount > 0 && checks.destinationValid && !checks.destinationKnown) issues.push('Destination should match an existing Node.Name.');
        if (!checks.filterValid) issues.push('Filter must be an object of array values or null.');
        return issues;
    }

    function getEdgeSchemaAdvisories(edgeValue, nodeNames = [], knownFilterKeys = []) {
        const checks = getEdgeSchemaChecks(edgeValue, nodeNames, knownFilterKeys);
        const advisories = [];
        if (checks.unknownFilterKeys.length) {
            advisories.push(`Filter key(s) not found in detected metadata fields: ${checks.unknownFilterKeys.join(', ')} (allowed by spec; verify spelling/context).`);
        }
        return advisories;
    }

    function createEdgeSchemaHint(edgeValue, nodeNames = [], knownFilterKeys = []) {
        const hint = document.createElement('div');
        const issues = getEdgeSchemaIssues(edgeValue, nodeNames, knownFilterKeys);
        const advisories = getEdgeSchemaAdvisories(edgeValue, nodeNames, knownFilterKeys);

        hint.className = issues.length
            ? 'small border rounded p-2 mb-2 bg-warning-subtle text-warning-emphasis'
            : 'small border rounded p-2 mb-2 bg-light-subtle text-muted';

        const summary = document.createElement('div');
        summary.className = 'fw-semibold';
        summary.textContent = issues.length
            ? 'Edge schema: missing or invalid required fields.'
            : 'Edge schema: required Source and Destination are present.';
        hint.appendChild(summary);

        if (issues.length) {
            const detail = document.createElement('div');
            detail.textContent = issues.join(' ');
            hint.appendChild(detail);
        }

        if (advisories.length) {
            const advisory = document.createElement('div');
            advisory.className = 'mt-1';
            advisory.textContent = advisories.join(' ');
            hint.appendChild(advisory);
        }

        const optional = document.createElement('div');
        optional.className = 'mt-1';
        optional.textContent = 'Optional Filter maps metadata keys (including contrast) to arrays; multiple keys are combined by conjunction.';
        hint.appendChild(optional);

        return hint;
    }

    function getTransformationsSchemaChecks(transformationsValue) {
        const knownKeys = ['Transformer', 'Instructions', 'GeneratedColumns'];
        const keys = transformationsValue && typeof transformationsValue === 'object' && !Array.isArray(transformationsValue)
            ? Object.keys(transformationsValue)
            : [];
        const unknownKeys = keys.filter(key => !knownKeys.includes(key));

        const transformerValue = typeof transformationsValue?.Transformer === 'string'
            ? transformationsValue.Transformer.trim()
            : '';
        const allowedTransformers = ['bidspm', 'pybids-transforms-v1'];
        const transformerValid = allowedTransformers.includes(transformerValue);
        const transformerPreferred = transformerValue === 'bidspm';

        const instructionsArray = Array.isArray(transformationsValue?.Instructions);
        const instructionsEntriesValid = instructionsArray && transformationsValue.Instructions.every(
            instruction => instruction && typeof instruction === 'object' && !Array.isArray(instruction) && typeof instruction.Name === 'string' && instruction.Name.trim() !== ''
        );

        const generatedColumns = transformationsValue?.GeneratedColumns;
        const generatedColumnsValid = generatedColumns === undefined
            || generatedColumns === null
            || (Array.isArray(generatedColumns) && generatedColumns.every(value => typeof value === 'string' && value.trim() !== ''));

        return {
            unknownKeys,
            transformerValue,
            transformerValid,
            transformerPreferred,
            instructionsArray,
            instructionsEntriesValid,
            instructionCount: instructionsArray ? transformationsValue.Instructions.length : 0,
            generatedColumnsValid,
            generatedColumnsCount: Array.isArray(generatedColumns) ? generatedColumns.length : 0,
            passedRequired: (transformerValid ? 1 : 0) + (instructionsArray ? 1 : 0),
            totalRequired: 2
        };
    }

    function getTransformationsSchemaIssues(transformationsValue) {
        const checks = getTransformationsSchemaChecks(transformationsValue);
        const issues = [];
        if (checks.unknownKeys.length) issues.push(`Unknown Transformations field(s): ${checks.unknownKeys.join(', ')}.`);
        if (!checks.transformerValid) issues.push('Transformer is required and should be bidspm (legacy pybids-transforms-v1 is also accepted).');
        if (!checks.instructionsArray) issues.push('Instructions is required and must be an array.');
        if (checks.instructionsArray && !checks.instructionsEntriesValid) issues.push('Each instruction should be an object with a non-empty Name.');
        if (!checks.generatedColumnsValid) issues.push('GeneratedColumns must be an array of non-empty strings when provided.');
        return issues;
    }

    function createTransformationsSchemaHint(transformationsValue) {
        const hint = document.createElement('div');
        const issues = getTransformationsSchemaIssues(transformationsValue);
        const checks = getTransformationsSchemaChecks(transformationsValue);

        hint.className = issues.length
            ? 'small border rounded p-2 mb-2 bg-warning-subtle text-warning-emphasis'
            : 'small border rounded p-2 mb-2 bg-light-subtle text-muted';

        const summary = document.createElement('div');
        summary.className = 'fw-semibold';
        summary.textContent = issues.length
            ? 'Transformations schema: missing or invalid required fields.'
            : 'Transformations schema: required Transformer and Instructions are present.';
        hint.appendChild(summary);

        if (issues.length) {
            const detail = document.createElement('div');
            detail.textContent = issues.join(' ');
            hint.appendChild(detail);
        }

        const optional = document.createElement('div');
        optional.className = 'mt-1';
        optional.textContent = checks.generatedColumnsCount
            ? 'GeneratedColumns is an editor convenience field; ensure strict schema output if you target external validators.'
            : (!checks.transformerPreferred && checks.transformerValid)
                ? 'Using legacy transformer id pybids-transforms-v1; bidspm is recommended for bidspm workflows.'
                : 'Instruction argument schema is transformer-specific (bidspm).';
        hint.appendChild(optional);

        return hint;
    }

    function getTopLevelSchemaChecks(modelValue) {
        const nameValid = typeof modelValue?.Name === 'string' && modelValue.Name.trim() !== '';
        const versionValue = typeof modelValue?.BIDSModelVersion === 'string' ? modelValue.BIDSModelVersion.trim() : '';
        const versionValid = versionValue !== '';
        const versionSemverLike = /^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$/.test(versionValue);

        const nodesArray = Array.isArray(modelValue?.Nodes);
        const nodesNonEmpty = nodesArray && modelValue.Nodes.length > 0;
        const nodeNames = nodesArray
            ? modelValue.Nodes.map(node => String(node?.Name || '').trim()).filter(Boolean)
            : [];
        const nodeNameUnique = nodeNames.length === new Set(nodeNames).size;

        const edgesProvided = modelValue?.Edges !== undefined && modelValue?.Edges !== null;
        const edgesArray = !edgesProvided || Array.isArray(modelValue?.Edges);
        const edgeRefsValid = !Array.isArray(modelValue?.Edges)
            ? true
            : modelValue.Edges.every(edge => {
                const source = String(edge?.Source || '').trim();
                const destination = String(edge?.Destination || '').trim();
                return source === '' || nodeNames.includes(source)
                    ? (destination === '' || nodeNames.includes(destination))
                    : false;
            });

        const inputTaskArray = Array.isArray(modelValue?.Input?.task);
        const inputTaskEntriesValid = !inputTaskArray
            ? false
            : modelValue.Input.task.every(task => typeof task === 'string' && task.trim() !== '');

        return {
            nameValid,
            versionValid,
            versionSemverLike,
            nodesArray,
            nodesNonEmpty,
            nodeNameUnique,
            nodeNameCount: nodeNames.length,
            edgesArray,
            edgeRefsValid,
            edgesCount: Array.isArray(modelValue?.Edges) ? modelValue.Edges.length : 0,
            edgesProvided,
            inputTaskArray,
            inputTaskEntriesValid,
            passedRequired: (nameValid ? 1 : 0) + (versionValid ? 1 : 0) + (nodesArray ? 1 : 0),
            totalRequired: 3
        };
    }

    function getTopLevelSchemaIssues(modelValue) {
        const checks = getTopLevelSchemaChecks(modelValue);
        const issues = [];
        if (!checks.nameValid) issues.push('Name is required.');
        if (!checks.versionValid) issues.push('BIDSModelVersion is required.');
        if (!checks.nodesArray) issues.push('Nodes is required and must be an array.');
        if (checks.nodesArray && !checks.nodesNonEmpty) issues.push('Nodes should contain at least one node.');
        if (checks.nodesArray && !checks.nodeNameUnique) issues.push('Node names should be unique to keep edges unambiguous.');
        if (!checks.edgesArray) issues.push('Edges must be an array when provided.');
        if (checks.edgesArray && !checks.edgeRefsValid) issues.push('Edges should reference existing node names in Source and Destination.');
        return issues;
    }

    function getTopLevelSchemaAdvisories(modelValue) {
        const checks = getTopLevelSchemaChecks(modelValue);
        const advisories = [];
        if (checks.versionValid && !checks.versionSemverLike) advisories.push('BIDSModelVersion is free-form but typically semver-like (for example 1.0.0).');
        if (!checks.inputTaskArray) advisories.push('Input.task is optional in schema, but strongly recommended for reproducible task-scoped models.');
        if (checks.inputTaskArray && !checks.inputTaskEntriesValid) advisories.push('Input.task entries should be non-empty strings.');
        if (!checks.edgesProvided && checks.nodesArray && checks.nodesNonEmpty) advisories.push('When Edges is absent, node order defines the implicit analysis chain.');
        return advisories;
    }

    function createTopLevelSchemaHint(modelValue) {
        const hint = document.createElement('div');
        const issues = getTopLevelSchemaIssues(modelValue);
        const advisories = getTopLevelSchemaAdvisories(modelValue);

        hint.className = issues.length
            ? 'small border rounded p-2 mb-2 bg-warning-subtle text-warning-emphasis'
            : 'small border rounded p-2 mb-2 bg-light-subtle text-muted';

        const summary = document.createElement('div');
        summary.className = 'fw-semibold';
        summary.textContent = issues.length
            ? 'Top-level schema: missing or inconsistent model-level fields.'
            : 'Top-level schema: required Name, BIDSModelVersion and Nodes are present.';
        hint.appendChild(summary);

        if (issues.length) {
            const detail = document.createElement('div');
            detail.textContent = issues.join(' ');
            hint.appendChild(detail);
        }

        if (advisories.length) {
            const advisory = document.createElement('div');
            advisory.className = 'mt-1';
            advisory.textContent = advisories.join(' ');
            hint.appendChild(advisory);
        }

        return hint;
    }

    window.BidspmAnalysisModelSchema = {
        computeModelEditorSummary,
        createContrastSchemaHint,
        createDummyContrastsSchemaHint,
        createEdgeSchemaHint,
        createHrfSchemaHint,
        createModelSchemaHint,
        createNodeSchemaHint,
        createOptionsSchemaHint,
        createTopLevelSchemaHint,
        createTransformationsSchemaHint,
        formatModelSectionLabel,
        getContrastSchemaChecks,
        getEdgeSchemaAdvisories,
        getEdgeSchemaChecks,
        getEdgeSchemaIssues,
        getHrfSchemaChecks,
        getKnownEdgeFilterMetadataKeys,
        getNodeSchemaChecks,
        getNodeSchemaIssues,
        getTopLevelSchemaChecks,
        isReadonlyModelPath,
        renderModelEditorSummary
    };
})();