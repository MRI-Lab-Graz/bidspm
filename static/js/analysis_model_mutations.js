(function () {
    function pathTokens(path) {
        const tokens = [];
        const rx = /([^.[\]]+)|\[(\d+)\]/g;
        let match;
        while ((match = rx.exec(path)) !== null) {
            if (match[1] !== undefined) tokens.push(match[1]);
            else tokens.push(Number(match[2]));
        }
        return tokens;
    }

    function getByPath(root, path) {
        return pathTokens(path).reduce((acc, tk) => (acc == null ? acc : acc[tk]), root);
    }

    function setByPath(root, path, value) {
        const tokens = pathTokens(path);
        if (!tokens.length) return;
        let cursor = root;
        for (let i = 0; i < tokens.length - 1; i++) {
            cursor = cursor[tokens[i]];
            if (cursor == null) return;
        }
        cursor[tokens[tokens.length - 1]] = value;
    }

    function parsePrimitiveInput(raw, original) {
        if (typeof original === 'number') {
            const parsed = Number(raw);
            return Number.isNaN(parsed) ? original : parsed;
        }
        if (typeof original === 'boolean') return raw === true || raw === 'true';
        if (original === null) return raw === '' ? null : raw;
        return String(raw);
    }

    function isNuisanceRegressor(value) {
        if (typeof value !== 'string') return false;
        return NUISANCE_REGRESSOR_RX.test(value.trim());
    }

    function getParticipantRegressorTerms(includeIntercept = true) {
        const participants = getModelEditorParticipantsInfo();
        const categorical = normalizeStringArray(participants.categorical_columns);
        const numeric = normalizeStringArray(participants.numeric_columns);
        const baseTerms = includeIntercept ? ['1'] : [];
        return Array.from(new Set([...baseTerms, ...categorical, ...numeric])).filter(Boolean);
    }

    function isFirstLevelNodeIndex(nodeIdx) {
        return Number(nodeIdx) === 0;
    }

    function getHigherLevelMetadataTerms(node) {
        return Array.from(new Set(
            normalizeStringArray(node?.GroupBy)
                .filter((term) => term && term !== 'contrast')
        )).filter(Boolean);
    }

    function inferGeneratedColumnsFromInstruction(instruction) {
        if (!instruction || typeof instruction !== 'object') return [];

        const opName = String(instruction.Name || '').trim();
        const outputValues = normalizeStringArray(instruction.Output);

        if (opName === 'LabelIdenticalRows' || opName === 'Label_identical_rows') {
            if (outputValues.length) return outputValues;
            return normalizeStringArray(instruction.Input).map((name) => `${name}_label`);
        }

        return outputValues;
    }

    function getTransformerModelXRegressorsForNode(node) {
        const transformations = (node?.Transformations && typeof node.Transformations === 'object' && !Array.isArray(node.Transformations))
            ? node.Transformations
            : null;
        const explicitGenerated = normalizeStringArray(transformations?.GeneratedColumns);
        const inferredGenerated = Array.isArray(transformations?.Instructions)
            ? Array.from(new Set(transformations.Instructions.flatMap((instruction) => inferGeneratedColumnsFromInstruction(instruction))))
            : [];

        return Array.from(new Set([...explicitGenerated, ...inferredGenerated])).filter((name) => {
            if (!name || name === '1') return false;
            if (name.startsWith('trial_type.') || name.startsWith('condition.')) return false;
            return true;
        });
    }

    function getHigherLevelRegressorTermsForNode(nodeIdx, includeIntercept = true) {
        const node = Array.isArray(modelEditorDraft?.Nodes) ? modelEditorDraft.Nodes[nodeIdx] : null;
        const baseTerms = includeIntercept ? ['1'] : [];
        return Array.from(new Set([
            ...baseTerms,
            ...getHigherLevelMetadataTerms(node),
            ...getParticipantRegressorTerms(false),
            ...getIncomingContrastNamesForNode(nodeIdx)
        ])).filter(Boolean);
    }

    function defaultArrayItemForPath(path) {
        if (path === 'Nodes') {
            const existingNodeCount = Array.isArray(modelEditorDraft?.Nodes) ? modelEditorDraft.Nodes.length : 0;
            if (existingNodeCount > 0) {
                return {
                    Level: 'Subject',
                    Name: 'subject_level',
                    GroupBy: ['contrast', 'subject'],
                    Model: {
                        X: ['1'],
                        Type: 'glm'
                    },
                    DummyContrasts: { Test: 't' },
                    Contrasts: []
                };
            }
            return {
                Level: 'Run',
                Name: 'run_level',
                GroupBy: ['run', 'subject'],
                Model: {
                    X: ['trial_type'],
                    HRF: { Variables: ['trial_type'], Model: 'spm' },
                    Type: 'glm',
                    Software: { SPM: { Model: 'spm' } }
                },
                Contrasts: []
            };
        }
        if (path === 'Edges') {
            return {
                Source: 'run',
                Destination: 'subject',
                Filter: {}
            };
        }
        if (/\.Contrasts$/.test(path)) {
            const defaultCondition = getDefaultConditionTokenForPath(path);
            return {
                Name: `Contrast_${Date.now().toString().slice(-4)}`,
                ConditionList: defaultCondition ? [defaultCondition] : [],
                Weights: defaultCondition ? [1] : [],
                Test: 't'
            };
        }
        if (/\.ConditionList$/.test(path)) return getDefaultConditionTokenForPath(path);
        if (/\.Weights$/.test(path)) return 0;
        if (/\.X$/.test(path)) {
            const suggestedRegressors = getSuggestedRegressorsForModelXPath(path);
            return suggestedRegressors[0] || 'trial_type';
        }
        if (/\.GroupBy$/.test(path)) return 'run';
        if (/\.Variables$/.test(path)) return 'trial_type';
        return '';
    }

    function addArrayItem(path) {
        const arr = getByPath(modelEditorDraft, path);
        if (!Array.isArray(arr)) return;
        arr.push(defaultArrayItemForPath(path));
    }

    function reorderArrayItem(arrayPath, fromIndex, toIndex) {
        const arr = getByPath(modelEditorDraft, arrayPath);
        if (!Array.isArray(arr)) return false;
        if (fromIndex === toIndex) return false;
        if (fromIndex < 0 || fromIndex >= arr.length) return false;
        if (toIndex < 0 || toIndex > arr.length) return false;

        const [moved] = arr.splice(fromIndex, 1);
        let targetIndex = toIndex;
        if (fromIndex < toIndex) targetIndex -= 1;
        arr.splice(targetIndex, 0, moved);
        return true;
    }

    function isModelXPath(path) {
        return /\.Model\.X\[\d+\]$/.test(path);
    }

    function isManagedModelHrfPath(path) {
        return /^Nodes\[\d+\]\.Model\.HRF$/.test(String(path || ''));
    }

    function isManagedModelHrfVariablesPath(path) {
        return /^Nodes\[\d+\]\.Model\.HRF\.Variables(?:\[\d+\])?$/.test(String(path || ''));
    }

    function isDuplicateModelXRegressor(path, candidate) {
        const match = path.match(/^(.*)\[(\d+)\]$/);
        if (!match) return false;

        const arrayPath = match[1];
        const index = Number(match[2]);
        const arr = getByPath(modelEditorDraft, arrayPath);
        if (!Array.isArray(arr)) return false;

        const normalized = String(candidate || '').trim();
        return arr.some((val, idx) => idx !== index && String(val || '').trim() === normalized);
    }

    function getModelObjectPathFromModelXPath(path) {
        const match = String(path || '').match(/^(.*)\.X(?:\[\d+\])?$/);
        return match ? match[1] : null;
    }

    function getModelObjectFromModelXPath(path) {
        const modelPath = getModelObjectPathFromModelXPath(path);
        if (!modelPath) return null;
        const modelObj = getByPath(modelEditorDraft, modelPath);
        if (!modelObj || typeof modelObj !== 'object' || Array.isArray(modelObj)) return null;
        if (!Array.isArray(modelObj.X)) modelObj.X = [];
        return modelObj;
    }

    function normalizeModelHrfVariables(modelObj) {
        if (!modelObj || !modelObj.HRF || typeof modelObj.HRF !== 'object' || Array.isArray(modelObj.HRF)) {
            return [];
        }
        const raw = Array.isArray(modelObj.HRF.Variables) ? modelObj.HRF.Variables : [];
        return Array.from(new Set(raw.map(value => String(value || '').trim()).filter(Boolean)));
    }

    function isHrfApplicableRegressor(regressor) {
        return String(regressor || '').trim() !== '1';
    }

    function syncModelXHrfVariables(path) {
        const modelObj = getModelObjectFromModelXPath(path);
        if (!modelObj || !modelObj.HRF || typeof modelObj.HRF !== 'object' || Array.isArray(modelObj.HRF)) {
            return;
        }

        const selected = new Set((Array.isArray(modelObj.X) ? modelObj.X : [])
            .map(value => String(value || '').trim())
            .filter(Boolean));
        const kept = normalizeModelHrfVariables(modelObj)
            .filter(regressor => selected.has(regressor) && isHrfApplicableRegressor(regressor));

        if (!kept.length) {
            delete modelObj.HRF;
            return;
        }

        modelObj.HRF = {
            ...modelObj.HRF,
            Model: String(modelObj.HRF.Model || 'spm').trim() || 'spm',
            Variables: kept
        };
    }

    function syncAllModelXHrfVariables() {
        if (!modelEditorDraft || typeof modelEditorDraft !== 'object') return;
        if (!Array.isArray(modelEditorDraft.Nodes)) return;

        modelEditorDraft.Nodes.forEach((node, idx) => {
            if (!node || typeof node !== 'object' || Array.isArray(node)) return;
            const modelObj = node.Model;
            if (!modelObj || typeof modelObj !== 'object' || Array.isArray(modelObj)) return;

            if (!Array.isArray(modelObj.X)) {
                modelObj.X = [];
            }
            modelObj.X = Array.from(new Set(modelObj.X.map(value => String(value || '').trim()).filter(Boolean)));
            syncModelXHrfVariables(`Nodes[${idx}].Model.X`);
        });
    }

    function isModelXRegressorHrfEnabled(path) {
        const modelObj = getModelObjectFromModelXPath(path);
        if (!modelObj) return false;
        const regressor = String(getByPath(modelEditorDraft, path) || '').trim();
        if (!regressor) return false;
        return normalizeModelHrfVariables(modelObj).includes(regressor);
    }

    function toggleModelXRegressorHrf(path) {
        const status = document.getElementById('model-editor-status');
        const modelObj = getModelObjectFromModelXPath(path);
        if (!modelObj) return;

        const regressor = String(getByPath(modelEditorDraft, path) || '').trim();
        if (!regressor) return;

        if (!isHrfApplicableRegressor(regressor)) {
            status.innerHTML = '<div class="alert alert-info py-1 x-small mb-2">Intercept is not HRF-convolved.</div>';
            return;
        }

        const current = normalizeModelHrfVariables(modelObj);
        if (current.includes(regressor)) {
            const next = current.filter(item => item !== regressor);
            if (next.length) {
                modelObj.HRF = {
                    ...modelObj.HRF,
                    Model: String(modelObj.HRF?.Model || 'spm').trim() || 'spm',
                    Variables: next
                };
            } else {
                delete modelObj.HRF;
            }
            status.innerHTML = `<div class="alert alert-info py-1 x-small mb-2">HRF off for ${regressor}</div>`;
            renderModelAccordionEditor();
            return;
        }

        if (!modelObj.HRF || typeof modelObj.HRF !== 'object' || Array.isArray(modelObj.HRF)) {
            modelObj.HRF = { Model: 'spm', Variables: [] };
        }
        modelObj.HRF.Model = String(modelObj.HRF.Model || 'spm').trim() || 'spm';
        modelObj.HRF.Variables = Array.from(new Set([...current, regressor]));
        status.innerHTML = `<div class="alert alert-info py-1 x-small mb-2">HRF on for ${regressor}</div>`;
        renderModelAccordionEditor();
    }

    function addRegressorToModelX(arrayPath, regressor, insertIndex = null) {
        const status = document.getElementById('model-editor-status');
        const arr = getByPath(modelEditorDraft, arrayPath);
        if (!Array.isArray(arr)) return;

        const normalized = String(regressor || '').trim();
        if (!normalized) return;

        if (arr.some(value => String(value || '').trim() === normalized)) {
            status.innerHTML = `<div class="alert alert-warning py-1 x-small mb-2">Regressor already selected: ${normalized}</div>`;
            return;
        }

        if (insertIndex === null || insertIndex === undefined || insertIndex < 0 || insertIndex > arr.length) {
            arr.push(normalized);
        } else {
            arr.splice(insertIndex, 0, normalized);
        }
        syncModelXHrfVariables(arrayPath);
        status.innerHTML = '';
        renderModelAccordionEditor();
    }

    function moveModelXRegressorByStep(arrayPath, index, step) {
        const arr = getByPath(modelEditorDraft, arrayPath);
        if (!Array.isArray(arr)) return false;
        if (step === 0) return false;

        const targetIndex = step < 0 ? index - 1 : index + 2;
        return reorderArrayItem(arrayPath, index, targetIndex);
    }

    function getSuggestedRegressorsForModelXPath(arrayPath) {
        const match = String(arrayPath || '').match(/^Nodes\[(\d+)\]\.Model\.X$/);
        if (!match) {
            return Array.from(new Set(modelEditorInterestRegressors || [])).filter(Boolean);
        }

        const nodeIdx = Number(match[1]);
        const node = Array.isArray(modelEditorDraft?.Nodes) ? modelEditorDraft.Nodes[nodeIdx] : null;
        const level = String(node?.Level || '').trim().toLowerCase();
        if (level === 'dataset') {
            return getParticipantRegressorTerms(true);
        }

        const transformerRegressors = getTransformerModelXRegressorsForNode(node);
        if (isFirstLevelNodeIndex(nodeIdx)) {
            return Array.from(new Set([
                ...(modelEditorInterestRegressors || []),
                ...transformerRegressors
            ])).filter(Boolean);
        }

        return Array.from(new Set([
            ...getHigherLevelRegressorTermsForNode(nodeIdx, true),
            ...transformerRegressors
        ])).filter(Boolean);
    }

    window.BidspmAnalysisModelMutations = {
        addArrayItem,
        addRegressorToModelX,
        defaultArrayItemForPath,
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
        pathTokens,
        reorderArrayItem,
        setByPath,
        syncAllModelXHrfVariables,
        syncModelXHrfVariables,
        toggleModelXRegressorHrf
    };
})();