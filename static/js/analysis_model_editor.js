// analysis_model_editor.js
// Extracted from templates/analysis.html: shared page state and the model-editor rendering/loading code (badges, pickers, section cards, BIDS task/regressor/group-by loaders).
// Classic script (shared globals); loaded before the inline bootstrap script in analysis.html.

const TRANSFORMER_LAUNCH_CONTEXT_KEY = 'bidspm.transformerLaunchContext';
const PENDING_TRANSFORMER_KEY = 'bidspm.pendingTransformerModel';

const terminal = document.getElementById('terminal');
const execStatus = document.getElementById('exec-status');
const validationResult = document.getElementById('validation-result');
const pathAlerts = document.getElementById('path-alerts');

// Both result panels sit below the (long) model editor section, far from
// the buttons that populate them -- scroll them into view so feedback
// isn't missed just because it renders off-screen.
function revealResult(el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
const modelHintsPanel = document.getElementById('model-hints-panel');

var {
    createModelHelperApi,
    emptyParticipantsInfo,
    normalizeStringArray
} = window.BidspmAnalysisModelPresets;

var eventSource = null;
var schema = {};
var unifiedStudyConfig = {};
var modelEditorDraft = null;
var modelEditorBidsTasks = [];
var modelEditorInterestRegressors = [];
var modelEditorEventSamples = { trial_type: [], condition: [] };
var modelEditorEventColumns = [];
var modelEditorEventNumericColumns = [];
var modelEditorEventNumericSamples = {};
var modelEditorConfoundColumns = [];
var modelEditorTransRotConfounds = [];
var modelEditorGroupByOptions = ['subject'];
var modelEditorInputEntityValues = {};
var modelEditorParticipantsInfo = emptyParticipantsInfo();
var showModelTechnicalPaths = false;
const MODEL_ADVANCED_FIELDS_STORAGE_KEY = 'bidspm_model_editor_show_advanced';
var showModelAdvancedFields = localStorage.getItem(MODEL_ADVANCED_FIELDS_STORAGE_KEY) === '1';

// ParametricModulations, Edge.Filter and node/edge Description are rarely used in
// practice (none of the production models we've checked -- studies/OL.json or any of
// studies/132/model_*.json -- set them) so they're hidden by default behind this badge
// unless "Show advanced fields" is on. Existing values are never altered by the toggle.
function createAdvancedFieldsBadge(text) {
    const badge = document.createElement('div');
    badge.className = 'small text-muted';
    badge.innerHTML = `<i class="fas fa-eye-slash me-1"></i>${text} (advanced — enable "Show advanced fields" to edit).`;
    return badge;
}

const {
    readTransformerLaunchContext,
    clearTransformerLaunchContext,
    areModelPathsEquivalent,
    readPendingTransformerPayload,
    clearPendingTransformerPayload
} = window.BidspmModelEditorLaunch.createLaunchHelpers({
    transformerLaunchContextKey: TRANSFORMER_LAUNCH_CONTEXT_KEY,
    pendingTransformerKey: PENDING_TRANSFORMER_KEY
});

const { consumePendingTransformerPayload } = window.BidspmModelEditorTransformerPayload.createTransformerPayloadHelpers({
    currentProjectId,
    getModel: () => modelEditorDraft,
    setModel: (nextModel) => { modelEditorDraft = nextModel; },
    areModelPathsEquivalent,
    readTransformerLaunchContext,
    readPendingTransformerPayload,
    normalizeStringArray,
    extendInterestRegressorPool
});
var modelEditorOpenPaths = new Set(); // tracks which accordion panels are open across re-renders
var modelEditorPendingOpenPaths = new Set();
var modelXDragState = null;

var {
    appendModelMetaPill,
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
    getDummyContrastsSchemaChecks,
    getEdgeSchemaAdvisories,
    getEdgeSchemaChecks,
    getEdgeSchemaIssues,
    getDirectFieldCompletion,
    getHrfSchemaChecks,
    getKnownEdgeFilterMetadataKeys,
    getModelPillTone,
    getNodeSchemaChecks,
    getNodeSchemaIssues,
    getOptionsSchemaChecks,
    getTopLevelSchemaChecks,
    getTransformationsSchemaChecks,
    isFilledModelValue,
    isReadonlyModelPath,
    renderModelEditorSummary
} = window.BidspmAnalysisModelSchema;

var {
    addArrayItem,
    addRegressorToModelX,
    getByPath,
    getModelObjectFromModelXPath,
    getModelObjectPathFromModelXPath,
    getSuggestedRegressorsForModelXPath,
    isDuplicateModelXRegressor,
    isHrfApplicableRegressor,
    isManagedModelHrfPath,
    isManagedModelHrfVariablesPath,
    isModelXPath,
    isModelXRegressorHrfEnabled,
    isNuisanceRegressor,
    moveModelXRegressorByStep,
    normalizeModelHrfVariables,
    parsePrimitiveInput,
    reorderArrayItem,
    setByPath,
    syncAllModelXHrfVariables,
    syncModelXHrfVariables,
    toggleModelXRegressorHrf
} = window.BidspmAnalysisModelMutations;

const refreshModelHints = (...args) => window.BidspmAnalysisModelHints.refreshModelHints({
    panel: modelHintsPanel,
    modelPath: () => document.getElementById('input-MODELS_FILE')?.value,
    bidsDir: () => document.getElementById('input-BIDS_DIR')?.value,
    getModelContentFromPath,
    fetchImpl: window.fetch.bind(window)
}, ...args);

var {
    applyDatasetNodePreset,
    buildNodeFromPreset,
    getDefaultConditionTokenForPath,
    getEdgeAvailableContrastNames,
    getIncomingContrastNamesForNode,
    getSuggestedConditionTermsForNode,
    getTransformerModelXRegressorsForNode
} = createModelHelperApi({
    getModelDraft: () => modelEditorDraft,
    getInterestRegressors: () => modelEditorInterestRegressors,
    getParticipantsInfo: () => getModelEditorParticipantsInfo(),
    getInputEntityValues: () => modelEditorInputEntityValues,
    getEventSamples: () => modelEditorEventSamples
});
window.getTransformerModelXRegressorsForNode = getTransformerModelXRegressorsForNode;

const { openBrowser } = window.BidspmAnalysisBrowser.createBrowserController({
    fetchImpl: window.fetch.bind(window),
    modalEl: document.getElementById('browseModal'),
    bootstrapImpl: window.bootstrap,
    promptImpl: window.prompt.bind(window),
    getElement: (id) => document.getElementById(id),
    getConfigFolderValue: () => document.getElementById('config-folder')?.value || '.',
    getInputValue: (targetKey) => document.getElementById(`input-${targetKey}`)?.value || '.',
    setTargetValue: (targetKey, path) => {
        if (targetKey === 'config-folder') {
            const configFolderInput = document.getElementById('config-folder');
            if (configFolderInput) configFolderInput.value = path;
            return;
        }

        const input = document.getElementById(`input-${targetKey}`);
        if (!input) return;
        input.value = path;
        input.dispatchEvent(new Event('change'));
    }
});

const { openContrastBuilder } = window.BidspmAnalysisContrastBuilder.createContrastBuilder({
    alertImpl: window.alert.bind(window),
    bootstrapImpl: window.bootstrap,
    getElement: (id) => document.getElementById(id),
    querySelectorAll: (selector) => document.querySelectorAll(selector),
    nuisanceRegressorRx: NUISANCE_REGRESSOR_RX,
    getModelDraft: () => modelEditorDraft,
    setModelDraft: (draft) => {
        modelEditorDraft = draft;
    },
    getInterestRegressors: () => modelEditorInterestRegressors,
    getIncomingContrastNamesForNode,
    getSuggestedConditionTermsForNode,
    getParticipantsInfo: () => getModelEditorParticipantsInfo(),
    getModelPath: () => document.getElementById('input-MODELS_FILE')?.value,
    getModelContentFromPath,
    loadBidsTasksForModelEditor,
    loadInterestRegressorsForModelEditor,
    loadGroupByOptionsForModelEditor,
    renderModelAccordionEditor
});
window.openContrastBuilder = openContrastBuilder;

var {
    stripLegacyGeneratedColumnsFromModel,
    updateModelJsonPreview
} = window.BidspmAnalysisPreviewValidation.createPreviewController({
    fetchImpl: window.fetch.bind(window),
    getElement: (id) => document.getElementById(id),
    getModelDraft: () => modelEditorDraft,
    validationUrl: '/validate_model'
});

var {
    createAddTransformationsPanel,
    createContrastManagerPanel,
    createDatasetModelPresetPanel,
    createDummyContrastsPanel,
    createEdgeWorkspaceFields,
    createNodeIdentityEditor,
    createNodeMaskPicker
} = window.BidspmAnalysisNodePanels.createNodePanelBuilders({
    alertImpl: window.alert.bind(window),
    fetchImpl: window.fetch.bind(window),
    createDummyContrastsSchemaHint,
    createTransformationsSchemaHint,
    getByPath: (path) => getByPath(modelEditorDraft, path),
    getElement: (id) => document.getElementById(id),
    getIncomingContrastNamesForNode,
    getParticipantsInfo: () => getModelEditorParticipantsInfo(),
    normalizeStringArray,
    openContrastBuilder,
    applyDatasetNodePreset,
    renderModelAccordionEditor,
    setModelEditorStatus,
    openTransformerBuilder,
    getModelEdges: () => Array.isArray(modelEditorDraft?.Edges) ? modelEditorDraft.Edges : [],
    getModelNodes: () => Array.isArray(modelEditorDraft?.Nodes) ? modelEditorDraft.Nodes : [],
    getInputEntityValues: () => modelEditorInputEntityValues,
    getEdgeAvailableContrastNames,
    isAdvancedFieldsVisible: () => showModelAdvancedFields,
    createAdvancedFieldsBadge
});

function getBranchBadgeDescriptors(path, value) {
    if (/^Nodes\[\d+\]$/.test(path) && value && typeof value === 'object') {
        const checks = getNodeSchemaChecks(value);
        const levelValue = typeof value.Level === 'string' ? value.Level.trim() : '';
        return [
            { text: `Required ${checks.passed}/${checks.total}`, tone: checks.passed === checks.total ? 'success' : 'warning' },
            { text: levelValue ? `Level ${levelValue}` : 'Level unset', tone: checks.levelValid ? 'success' : 'warning' },
            { text: `Contrasts ${Array.isArray(value.Contrasts) ? value.Contrasts.length : 0}`, tone: 'neutral' }
        ];
    }

    if (/\.Model$/.test(path) && value && typeof value === 'object') {
        const typeValue = typeof value.Type === 'string' ? value.Type.trim() : '';
        const typeValid = ['glm', 'meta'].includes(typeValue);
        const hasX = Array.isArray(value.X);
        const requiredCount = (typeValid ? 1 : 0) + (hasX ? 1 : 0);
        const optionalCount = ['Formula', 'HRF', 'Options', 'Software'].filter(key => value[key] !== undefined && value[key] !== null).length;
        const regressorCount = hasX ? value.X.length : 0;
        return [
            { text: `Required ${requiredCount}/2`, tone: requiredCount === 2 ? 'success' : 'warning' },
            { text: typeValue ? `Type ${typeValue}` : 'Type unset', tone: typeValid ? 'success' : 'warning' },
            { text: `Regressors ${regressorCount}`, tone: hasX ? 'success' : 'warning' },
            { text: `Optional ${optionalCount}/4`, tone: optionalCount ? 'neutral' : 'neutral' }
        ];
    }

    if (/\.Model\.HRF$/.test(path) && value && typeof value === 'object') {
        const modelObj = getByPath(modelEditorDraft, path.replace(/\.HRF$/, ''));
        const modelX = Array.isArray(modelObj?.X)
            ? modelObj.X.map(item => String(item || '').trim()).filter(Boolean)
            : [];
        const checks = getHrfSchemaChecks(value, modelX);
        const kernel = checks.modelValid ? String(value.Model).trim() : '';
        return [
            { text: `Required ${checks.passedRequired}/${checks.totalRequired}`, tone: checks.passedRequired === checks.totalRequired ? 'success' : 'warning' },
            { text: kernel ? `Kernel ${kernel}` : 'Kernel unset', tone: checks.modelValid ? 'success' : 'warning' },
            { text: `Variables ${checks.variableCount}`, tone: checks.variablesArray && checks.variablesEntriesValid ? 'success' : 'warning' },
            { text: checks.variablesEntriesValid && checks.variablesInX ? 'Subset of Model.X' : 'Variables outside Model.X', tone: checks.variablesEntriesValid && checks.variablesInX ? 'neutral' : 'warning' }
        ];
    }

    if (/\.Model\.Options$/.test(path) && value && typeof value === 'object') {
        const checks = getOptionsSchemaChecks(value);
        const allValid = !checks.unknownKeys.length
            && checks.highPassValid
            && checks.lowPassValid
            && checks.replaceVariablesValid
            && checks.maskValid
            && checks.aggregateValid;
        return [
            { text: allValid ? 'Valid fields' : 'Invalid fields', tone: allValid ? 'success' : 'warning' },
            { text: `Provided ${checks.providedCount}`, tone: checks.providedCount ? 'neutral' : 'neutral' },
            { text: checks.unknownKeys.length ? `Unknown ${checks.unknownKeys.length}` : 'Known keys', tone: checks.unknownKeys.length ? 'warning' : 'neutral' }
        ];
    }

    if (/\.Contrasts\[\d+\]$/.test(path) && value && typeof value === 'object') {
        const checks = getContrastSchemaChecks(value);
        const testValue = typeof value.Test === 'string' ? value.Test.trim() : '';
        return [
            { text: `Required ${checks.passedRequired}/${checks.totalRequired}`, tone: checks.passedRequired === checks.totalRequired ? 'success' : 'warning' },
            { text: testValue ? `Test ${testValue}` : 'Test unset', tone: checks.testValid ? 'success' : 'warning' },
            { text: `Conditions ${checks.conditionCount}`, tone: checks.conditionListValid ? 'success' : 'warning' },
            { text: checks.matrixWeights ? `Weight rows ${checks.weightCount}` : `Weights ${checks.weightCount}`, tone: checks.weightsValid ? 'success' : 'warning' }
        ];
    }

    if (/\.DummyContrasts$/.test(path) && value && typeof value === 'object') {
        const modelObj = getByPath(modelEditorDraft, path.replace(/\.DummyContrasts$/, '.Model'));
        const modelX = Array.isArray(modelObj?.X)
            ? modelObj.X.map(item => String(item || '').trim()).filter(Boolean)
            : [];
        const checks = getDummyContrastsSchemaChecks(value, modelX);
        const testLabel = checks.testValue || 'unset';
        return [
            { text: `Required ${checks.passedRequired}/${checks.totalRequired}`, tone: checks.passedRequired === checks.totalRequired ? 'success' : 'warning' },
            { text: `Test ${testLabel}`, tone: checks.testValid ? 'success' : 'warning' },
            { text: `Contrasts ${checks.contrastsCount}`, tone: checks.contrastsArray && checks.contrastsEntriesValid ? 'success' : 'warning' },
            { text: checks.subsetCheckApplicable ? (checks.contrastsSubsetValid ? 'Subset of Model.X' : 'Outside Model.X') : 'Subset unchecked', tone: checks.subsetCheckApplicable ? (checks.contrastsSubsetValid ? 'neutral' : 'warning') : 'neutral' }
        ];
    }

    if (/^Edges\[\d+\]$/.test(path) && value && typeof value === 'object') {
        const nodeNames = Array.isArray(modelEditorDraft?.Nodes)
            ? modelEditorDraft.Nodes.map(node => String(node?.Name || '').trim()).filter(Boolean)
            : [];
        const knownFilterKeys = getKnownEdgeFilterMetadataKeys();
        const checks = getEdgeSchemaChecks(value, nodeNames, knownFilterKeys);
        return [
            { text: `Required ${checks.passedRequired}/${checks.totalRequired}`, tone: checks.passedRequired === checks.totalRequired ? 'success' : 'warning' },
            { text: checks.sourceValue ? `Source ${checks.sourceValue}` : 'Source unset', tone: checks.sourceValid && checks.sourceKnown ? 'success' : 'warning' },
            { text: checks.destinationValue ? `Dest ${checks.destinationValue}` : 'Dest unset', tone: checks.destinationValid && checks.destinationKnown ? 'success' : 'warning' },
            { text: checks.filterProvided ? `Filter keys ${checks.filterKeyCount}` : 'Filter none', tone: checks.filterValid ? 'neutral' : 'warning' },
            { text: checks.unknownFilterKeys.length ? `Unknown filter keys ${checks.unknownFilterKeys.length}` : 'Known filter keys', tone: checks.unknownFilterKeys.length ? 'warning' : 'neutral' }
        ];
    }

    if (/\.Transformations$/.test(path) && value && typeof value === 'object') {
        const checks = getTransformationsSchemaChecks(value);
        return [
            { text: `Required ${checks.passedRequired}/${checks.totalRequired}`, tone: checks.passedRequired === checks.totalRequired ? 'success' : 'warning' },
            { text: checks.transformerValid ? 'Transformer ok' : 'Transformer unset', tone: checks.transformerValid ? 'success' : 'warning' },
            { text: `Instructions ${checks.instructionCount}`, tone: checks.instructionsArray && checks.instructionsEntriesValid ? 'success' : 'warning' },
            { text: checks.unknownKeys.length ? `Unknown ${checks.unknownKeys.length}` : 'Known keys', tone: checks.unknownKeys.length ? 'warning' : 'neutral' }
        ];
    }

    if (/\.Contrasts$/.test(path) && Array.isArray(value)) {
        return [{ text: `${value.length} contrast${value.length === 1 ? '' : 's'}`, tone: value.length > 0 ? 'success' : 'neutral' }];
    }

    if (/\.GroupBy$/.test(path) && Array.isArray(value)) {
        return [{ text: `${value.length} grouping entr${value.length === 1 ? 'y' : 'ies'}`, tone: value.length > 0 ? 'success' : 'neutral' }];
    }

    if (/\.ConditionList$/.test(path) && Array.isArray(value)) {
        return [{ text: `${value.length} condition${value.length === 1 ? '' : 's'}`, tone: value.length > 0 ? 'success' : 'neutral' }];
    }

    if (Array.isArray(value)) {
        return [{ text: `${value.length} item${value.length === 1 ? '' : 's'}`, tone: value.length > 0 ? 'neutral' : 'neutral' }];
    }

    if (value && typeof value === 'object') {
        const stats = getDirectFieldCompletion(value);
        return [{ text: `Fields ${stats.filled}/${stats.total}`, tone: getModelPillTone(stats.filled, stats.total) }];
    }

    return [];
}

function createModelTaskPicker() {
    const taskCard = document.createElement('div');
    taskCard.className = 'model-task-picker';

    const taskTitle = document.createElement('div');
    taskTitle.className = 'model-task-picker-title';
    taskTitle.textContent = 'Input.task (from BIDS folder)';
    taskCard.appendChild(taskTitle);

    const taskText = document.createElement('div');
    taskText.className = 'small text-muted mb-2';
    taskText.textContent = 'Select one or more detected tasks. This stays locked to the BIDS folder scan.';
    taskCard.appendChild(taskText);

    if (!Array.isArray(modelEditorDraft.Input?.task)) {
        if (!modelEditorDraft.Input || typeof modelEditorDraft.Input !== 'object') {
            modelEditorDraft.Input = {};
        }
        modelEditorDraft.Input.task = [];
    }

    if (!modelEditorBidsTasks.length) {
        const warn = document.createElement('div');
        warn.className = 'text-muted small';
        warn.textContent = 'No BIDS tasks detected. Set a valid BIDS folder first.';
        taskCard.appendChild(warn);
        return taskCard;
    }

    const wrap = document.createElement('div');
    wrap.className = 'd-flex flex-wrap gap-2';
    modelEditorBidsTasks.forEach(task => {
        const pill = document.createElement('label');
        const isActive = modelEditorDraft.Input.task.includes(task);
        pill.className = `model-task-pill ${isActive ? 'active' : ''}`;

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = isActive;
        checkbox.addEventListener('change', () => {
            const set = new Set(modelEditorDraft.Input.task || []);
            if (checkbox.checked) set.add(task);
            else set.delete(task);
            modelEditorDraft.Input.task = Array.from(set);
            renderModelAccordionEditor();
        });

        pill.appendChild(checkbox);
        pill.appendChild(document.createTextNode(task));
        wrap.appendChild(pill);
    });
    taskCard.appendChild(wrap);

    return taskCard;
}

function createModelSessionRunPicker() {
    const entityValues = (modelEditorInputEntityValues && typeof modelEditorInputEntityValues === 'object')
        ? modelEditorInputEntityValues : {};
    const availableSessions = Array.isArray(entityValues.session) ? entityValues.session.map(String).filter(Boolean) : [];
    const availableRuns = Array.isArray(entityValues.run) ? entityValues.run.map(String).filter(Boolean) : [];

    if (!availableSessions.length && !availableRuns.length) return null;

    if (!modelEditorDraft.Input || typeof modelEditorDraft.Input !== 'object') modelEditorDraft.Input = {};

    const wrap = document.createElement('div');
    wrap.className = 'model-task-picker';

    function buildFilterSection(filterKey, availableValues) {
        const section = document.createElement('div');
        if (wrap.childElementCount > 0) section.className = 'mt-2 pt-2 border-top';

        const title = document.createElement('div');
        title.className = 'model-task-picker-title';
        title.textContent = `Input.${filterKey} (from BIDS folder)`;
        section.appendChild(title);

        const hint = document.createElement('div');
        hint.className = 'small text-muted mb-2';
        hint.textContent = `Restrict to specific ${filterKey}s. Leave all unchecked to include all.`;
        section.appendChild(hint);

        const pillRow = document.createElement('div');
        pillRow.className = 'd-flex flex-wrap gap-2';
        availableValues.forEach(val => {
            const pill = document.createElement('label');
            const isActive = Array.isArray(modelEditorDraft.Input[filterKey]) && modelEditorDraft.Input[filterKey].includes(val);
            pill.className = `model-task-pill ${isActive ? 'active' : ''}`;

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = isActive;
            checkbox.addEventListener('change', () => {
                const set = new Set(modelEditorDraft.Input[filterKey] || []);
                if (checkbox.checked) set.add(val);
                else set.delete(val);
                modelEditorDraft.Input[filterKey] = Array.from(set);
                if (!modelEditorDraft.Input[filterKey].length) delete modelEditorDraft.Input[filterKey];
                renderModelAccordionEditor();
            });

            pill.appendChild(checkbox);
            pill.appendChild(document.createTextNode(val));
            pillRow.appendChild(pill);
        });
        section.appendChild(pillRow);
        return section;
    }

    if (availableSessions.length) wrap.appendChild(buildFilterSection('session', availableSessions));
    if (availableRuns.length) wrap.appendChild(buildFilterSection('run', availableRuns));

    return wrap;
}

function createInlineNote(message) {
    const note = document.createElement('div');
    note.className = 'model-inline-note';
    note.textContent = message;
    return note;
}

function getModelEditorParticipantsInfo() {
    return (modelEditorParticipantsInfo && typeof modelEditorParticipantsInfo === 'object')
        ? modelEditorParticipantsInfo
        : emptyParticipantsInfo();
}

function setModelEditorStatus(message = '', tone = 'info') {
    const status = document.getElementById('model-editor-status');
    if (!status) return;
    status.innerHTML = message
        ? `<div class="alert alert-${tone} py-1 x-small mb-2">${message}</div>`
        : '';
}

function renderModelSectionContent(body, section) {
    if (section.kind === 'input') {
        body.appendChild(createModelTaskPicker());
        const sessionRunPicker = createModelSessionRunPicker();
        if (sessionRunPicker) body.appendChild(sessionRunPicker);
        const MANAGED_INPUT_KEYS = new Set(['task', 'session', 'run']);
        const extraInput = section.value && typeof section.value === 'object'
            ? Object.fromEntries(Object.entries(section.value).filter(([key]) => !MANAGED_INPUT_KEYS.has(key)))
            : {};

        if (Object.keys(extraInput).length > 0) {
            renderJsonEditor(body, extraInput, 'Input', false, 0);
        } else {
            body.appendChild(createInlineNote('Additional input properties will appear here if the model defines them.'));
        }
        return;
    }

    if (section.kind === 'overview') {
        body.appendChild(createTopLevelSchemaHint(modelEditorDraft));

        // Name and Description are always shown here as plain editable rows.
        // BIDSModelVersion is intentionally not rendered -- it's a locked,
        // non-editable schema field (see READONLY_MODEL_PATHS) and Description
        // is shown unconditionally rather than gated behind "Show advanced
        // fields" (that gate exists for the rarely-used per-node/per-edge
        // Description fields, not this top-level one).
        createPrimitiveRow(body, 'Name', modelEditorDraft?.Name ?? '', 'Name', false, 0);
        createPrimitiveRow(body, 'Description', modelEditorDraft?.Description ?? '', 'Description', false, 0);

        const extraKeys = Object.keys(section.value).filter(key => key !== 'Name' && key !== 'Description');
        if (extraKeys.length) {
            const extraValue = Object.fromEntries(extraKeys.map(key => [key, section.value[key]]));
            renderJsonEditor(body, extraValue, '', false, 0);
        }
        return;
    }

    if (section.kind === 'nodes' && (!Array.isArray(section.value) || section.value.length === 0)) {
        body.appendChild(createInlineNote('No nodes defined yet. Use Add Node in the header to create the first analysis node.'));
        return;
    }

    if ((section.kind === 'array' || section.kind === 'object') && !isFilledModelValue(section.value)) {
        body.appendChild(createInlineNote(`${section.label} is currently empty.`));
        return;
    }

    renderJsonEditor(body, section.value, section.path, false, 0);
}

function createModelSectionCard(container, section) {
    const card = document.createElement('div');
    const sectionThemeMap = {
        '__section_overview': 'section-overview',
        'Input': 'section-input',
        'Nodes': 'section-nodes',
        'Edges': 'section-edges'
    };
    const sectionThemeClass = sectionThemeMap[section.statePath] || 'section-generic';
    card.className = `model-section-card ${sectionThemeClass}`;

    const idBase = `model-section-${section.statePath.replace(/[^a-zA-Z0-9]/g, '-')}`;
    const headerId = `${idBase}-h`;
    const collapseId = `${idBase}-c`;

    const header = document.createElement('h2');
    header.className = 'accordion-header';
    header.id = headerId;

    const headerWrap = document.createElement('div');
    headerWrap.className = 'd-flex align-items-center gap-2';

    const button = document.createElement('button');
    button.className = `accordion-button model-section-toggle ${sectionThemeClass}`;
    button.type = 'button';
    button.setAttribute('data-bs-toggle', 'collapse');
    button.setAttribute('data-bs-target', `#${collapseId}`);
    button.setAttribute('aria-controls', collapseId);

    const title = document.createElement('span');
    title.className = 'model-section-title';

    const icon = document.createElement('span');
    icon.className = 'model-section-icon';
    icon.innerHTML = `<i class="fas ${section.icon}"></i>`;

    const heading = document.createElement('span');
    heading.className = 'model-section-heading';

    const label = document.createElement('span');
    label.className = 'model-section-label';
    label.textContent = section.label;

    const subtitle = document.createElement('span');
    subtitle.className = 'model-section-subtitle';
    subtitle.textContent = showModelTechnicalPaths && section.path
        ? section.path
        : section.stats.subtitle;

    heading.appendChild(label);
    heading.appendChild(subtitle);
    title.appendChild(icon);
    title.appendChild(heading);

    const meta = document.createElement('span');
    meta.className = 'model-section-meta';
    section.stats.badges.forEach(badge => appendModelMetaPill(meta, badge.text, badge.tone));

    button.appendChild(title);
    button.appendChild(meta);
    headerWrap.appendChild(button);

    if (section.kind === 'nodes' || section.kind === 'array') {
        if (section.kind === 'nodes') {
            const addNodeFromPreset = (presetValue) => {
                let nodeList = getByPath(modelEditorDraft, section.path);
                if (!Array.isArray(nodeList)) {
                    setByPath(modelEditorDraft, section.path, []);
                }
                nodeList = getByPath(modelEditorDraft, section.path);
                if (!Array.isArray(nodeList)) {
                    setModelEditorStatus('Could not create node list for this section.', 'danger');
                    return;
                }

                const result = buildNodeFromPreset(presetValue);
                nodeList.push(result.node);
                const newIndex = nodeList.length - 1;

                let edgeCreated = false;
                if (newIndex > 0) {
                    let edgeList = getByPath(modelEditorDraft, 'Edges');
                    if (!Array.isArray(edgeList)) {
                        setByPath(modelEditorDraft, 'Edges', []);
                    }
                    edgeList = getByPath(modelEditorDraft, 'Edges');
                    if (Array.isArray(edgeList)) {
                        const sourceName = String(nodeList[newIndex - 1]?.Name || '').trim();
                        const destinationName = String(nodeList[newIndex]?.Name || '').trim();
                        if (sourceName && destinationName) {
                            const hasEdge = edgeList.some(edge =>
                                String(edge?.Source || '').trim() === sourceName
                                && String(edge?.Destination || '').trim() === destinationName
                            );
                            if (!hasEdge) {
                                edgeList.push({ Source: sourceName, Destination: destinationName });
                                edgeCreated = true;
                            }
                        }
                    }
                }

                modelEditorPendingOpenPaths.add(section.statePath);
                modelEditorPendingOpenPaths.add(`${section.path}[${newIndex}]`);
                if (edgeCreated) modelEditorPendingOpenPaths.add('Edges');
                renderModelAccordionEditor();
                const edgeNote = edgeCreated ? ' Added linking edge.' : '';
                setModelEditorStatus(`${result.message}${edgeNote}`, result.tone || 'success');
            };

            const addGroup = document.createElement('div');
            addGroup.className = 'btn-group btn-group-sm json-add-btn';

            const quickAddBtn = document.createElement('button');
            quickAddBtn.type = 'button';
            quickAddBtn.className = 'btn btn-sm btn-success';
            quickAddBtn.textContent = '+ Add Node';
            quickAddBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                addNodeFromPreset('run_basic');
            });
            addGroup.appendChild(quickAddBtn);

            const addBtn = document.createElement('button');
            addBtn.type = 'button';
            addBtn.className = 'btn btn-sm btn-success dropdown-toggle dropdown-toggle-split';
            addBtn.innerHTML = '<span class="visually-hidden">Node presets</span>';
            addBtn.setAttribute('data-bs-toggle', 'dropdown');
            addBtn.setAttribute('aria-expanded', 'false');
            addBtn.setAttribute('aria-label', 'Node presets');
            addGroup.appendChild(addBtn);

            const menu = document.createElement('div');
            menu.className = 'dropdown-menu dropdown-menu-end';
            [
                ['run_basic', 'Run node'],
                ['session_basic', 'Session node'],
                ['subject_fixed', 'Subject node: fixed effects'],
                ['dataset_basic', 'Dataset node']
            ].forEach(([value, label]) => {
                const item = document.createElement('button');
                item.type = 'button';
                item.className = 'dropdown-item';
                item.textContent = label;
                item.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    addNodeFromPreset(value);
                });
                menu.appendChild(item);
            });
            addGroup.appendChild(menu);
            headerWrap.appendChild(addGroup);
        } else {
            const addBtn = document.createElement('button');
            addBtn.type = 'button';
            addBtn.className = 'btn btn-sm btn-outline-success json-add-btn';
            addBtn.textContent = '+ Add';
            addBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const current = getByPath(modelEditorDraft, section.path);
                if (!Array.isArray(current)) {
                    setByPath(modelEditorDraft, section.path, []);
                }
                if (!Array.isArray(getByPath(modelEditorDraft, section.path))) {
                    modelEditorDraft[section.path] = [];
                }
                addArrayItem(section.path);
                renderModelAccordionEditor();
            });
            headerWrap.appendChild(addBtn);
        }
    }

    header.appendChild(headerWrap);

    const collapse = document.createElement('div');
    collapse.id = collapseId;
    collapse.dataset.jsonPath = section.statePath;
    const wasOpen = modelEditorOpenPaths.has(section.statePath);
    collapse.className = `accordion-collapse collapse ${wasOpen ? 'show' : ''}`;
    button.className = `accordion-button model-section-toggle ${sectionThemeClass} ${wasOpen ? '' : 'collapsed'}`;
    button.setAttribute('aria-expanded', wasOpen ? 'true' : 'false');
    collapse.setAttribute('aria-labelledby', headerId);

    const body = document.createElement('div');
    body.className = 'model-section-body';
    renderModelSectionContent(body, section);
    collapse.appendChild(body);

    card.appendChild(header);
    card.appendChild(collapse);
    container.appendChild(card);
}

function pruneEdgesForCurrentNodes() {
    const edges = getByPath(modelEditorDraft, 'Edges');
    if (!Array.isArray(edges)) return;

    const nodes = Array.isArray(modelEditorDraft?.Nodes) ? modelEditorDraft.Nodes : [];
    const nodeNames = new Set(
        nodes
            .map(node => String(node?.Name || '').trim())
            .filter(Boolean)
    );

    const filteredEdges = edges.filter(edge => {
        const source = String(edge?.Source || '').trim();
        const destination = String(edge?.Destination || '').trim();
        if (!source || !destination) return false;
        return nodeNames.has(source) && nodeNames.has(destination);
    });

    setByPath(modelEditorDraft, 'Edges', filteredEdges);
}

function removeArrayItem(path) {
    const match = path.match(/^(.*)\[(\d+)\]$/);
    if (!match) return;

    const arrayPath = match[1];
    const index = Number(match[2]);
    const arr = getByPath(modelEditorDraft, arrayPath);
    if (!Array.isArray(arr)) return;
    if (index < 0 || index >= arr.length) return;

    arr.splice(index, 1);
    if (arrayPath === 'Nodes') {
        pruneEdgesForCurrentNodes();
    }
    if (/\.Model\.X$/.test(arrayPath)) {
        syncModelXHrfVariables(arrayPath);
    }
}

async function loadBidsTasksForModelEditor() {
    const bidsDir = document.getElementById('input-BIDS_DIR')?.value?.trim();
    if (!bidsDir) {
        throw new Error('Set BIDS Folder before editing model JSON.');
    }

    const res = await fetch(`/get_bids_tasks?path=${encodeURIComponent(bidsDir)}`);
    const tasks = await res.json();
    if (!Array.isArray(tasks) || tasks.length === 0) {
        throw new Error('No tasks detected in BIDS folder. Please check BIDS Folder path.');
    }

    modelEditorBidsTasks = tasks;
    return tasks;
}

// Forget everything learned from the BIDS dataset (event columns, confounds, participants).
function resetModelEditorHints() {
    modelEditorInterestRegressors = [];
    modelEditorEventSamples = { trial_type: [], condition: [] };
    modelEditorEventColumns = [];
    modelEditorEventNumericColumns = [];
    modelEditorEventNumericSamples = {};
    modelEditorConfoundColumns = [];
    modelEditorTransRotConfounds = [];
    modelEditorParticipantsInfo = emptyParticipantsInfo();
}

async function loadInterestRegressorsForModelEditor(modelContent) {
    const bidsDir = document.getElementById('input-BIDS_DIR')?.value?.trim();
    if (!bidsDir) {
        resetModelEditorHints();
        return [];
    }

    try {
        const response = await fetch('/api/model_hints', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model_content: modelContent,
                bids_dir: bidsDir,
                fmriprep_dir: document.getElementById('input-FMRIPREP_DIR')?.value?.trim() || ''
            })
        });
        const data = await response.json();
        const events = data?.dataset?.events || {};
        const sample = events.sample_values || {};
        modelEditorEventSamples = {
            trial_type: normalizeStringArray(sample.trial_type),
            condition: normalizeStringArray(sample.condition)
        };
        modelEditorEventColumns = normalizeStringArray(events.event_columns);
        modelEditorEventNumericColumns = normalizeStringArray(events.numeric_columns);
        const numericSamplesRaw = (events.numeric_sample_values && typeof events.numeric_sample_values === 'object')
            ? events.numeric_sample_values
            : {};
        const numericSamples = {};
        Object.entries(numericSamplesRaw).forEach(([columnName, values]) => {
            numericSamples[String(columnName || '').trim()] = normalizeStringArray(values);
        });
        modelEditorEventNumericSamples = numericSamples;
        const confounds = data?.dataset?.confounds || {};
        modelEditorConfoundColumns = normalizeStringArray(confounds.columns);
        modelEditorTransRotConfounds = normalizeStringArray(confounds.trans_rot_present);
        modelEditorParticipantsInfo = (data?.dataset?.participants && typeof data.dataset.participants === 'object')
            ? data.dataset.participants
            : emptyParticipantsInfo();
        const transformed = Array.isArray(data?.model?.transformed_columns)
            ? data.model.transformed_columns.map(v => String(v || '').trim()).filter(Boolean)
            : [];

        const trialRegs = modelEditorEventSamples.trial_type.map(v => `trial_type.${v}`);
        const conditionRegs = modelEditorEventSamples.condition.map(v => `condition.${v}`);

        modelEditorInterestRegressors = Array.from(new Set([
            ...trialRegs,
            ...conditionRegs,
            ...transformed
        ])).filter(Boolean);
        return modelEditorInterestRegressors;
    } catch (e) {
        console.warn('Could not load interest regressors:', e);
        resetModelEditorHints();
        return [];
    }
}

async function loadGroupByOptionsForModelEditor() {
    const bidsDir = document.getElementById('input-BIDS_DIR')?.value?.trim();
    if (!bidsDir) {
        modelEditorGroupByOptions = ['subject'];
        modelEditorInputEntityValues = {};
        return modelEditorGroupByOptions;
    }

    try {
        const res = await fetch(`/api/bids_entities?path=${encodeURIComponent(bidsDir)}`);
        const data = await res.json();
        if (Array.isArray(data.groupby_options) && data.groupby_options.length > 0) {
            modelEditorGroupByOptions = data.groupby_options;
        } else {
            modelEditorGroupByOptions = ['subject'];
        }
        modelEditorInputEntityValues = (data && data.values && typeof data.values === 'object') ? data.values : {};
    } catch (e) {
        modelEditorGroupByOptions = ['subject'];
        modelEditorInputEntityValues = {};
    }

    return modelEditorGroupByOptions;
}
