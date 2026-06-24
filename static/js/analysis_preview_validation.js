(function () {
    function createPreviewController(config = {}) {
        const fetchImpl = config.fetchImpl || window.fetch.bind(window);
        const getElement = config.getElement || ((id) => document.getElementById(id));
        const getModelDraft = config.getModelDraft || (() => null);
        const validationUrl = config.validationUrl || '/validate_model';
        const previewValidationState = { timer: null, runId: 0 };

        function stripLegacyGeneratedColumnsFromModel(input) {
            if (!input || typeof input !== 'object') return input;

            const clone = structuredClone(input);
            const walk = (value) => {
                if (!value || typeof value !== 'object') return;
                if (Array.isArray(value)) {
                    value.forEach((item) => walk(item));
                    return;
                }

                if (value.Transformations && typeof value.Transformations === 'object' && !Array.isArray(value.Transformations)) {
                    delete value.Transformations.GeneratedColumns;
                }

                // An empty Contrasts array is invalid per the BIDS Stats Models spec --
                // omitting the key (rather than "[]") is what "no contrasts" means.
                if (Array.isArray(value.Contrasts) && !value.Contrasts.length) {
                    delete value.Contrasts;
                }
                if (value.DummyContrasts && typeof value.DummyContrasts === 'object' && !Array.isArray(value.DummyContrasts)) {
                    if (Array.isArray(value.DummyContrasts.Contrasts) && !value.DummyContrasts.Contrasts.length) {
                        delete value.DummyContrasts.Contrasts;
                    }
                }

                Object.values(value).forEach((entry) => walk(entry));
            };

            walk(clone);
            return clone;
        }

        function setModelPreviewValidationState(state, message) {
            const badge = getElement('model-preview-validation-badge');
            const text = getElement('model-preview-validation-text');
            if (!badge || !text) return;

            const badgeMap = {
                idle: 'bg-secondary',
                checking: 'bg-info text-dark',
                valid: 'bg-success',
                invalid: 'bg-danger',
                error: 'bg-warning text-dark'
            };

            badge.className = `badge ${badgeMap[state] || 'bg-secondary'}`;
            badge.textContent = state;
            text.textContent = message;
        }

        function scheduleModelPreviewValidation() {
            if (previewValidationState.timer) {
                clearTimeout(previewValidationState.timer);
            }
            previewValidationState.timer = setTimeout(() => {
                validateModelPreviewLive();
            }, 250);
        }

        async function validateModelPreviewLive() {
            const runId = ++previewValidationState.runId;
            const modelDraft = getModelDraft();

            if (!modelDraft || typeof modelDraft !== 'object') {
                setModelPreviewValidationState('idle', 'Load a model to run live schema validation.');
                return;
            }

            const snapshot = stripLegacyGeneratedColumnsFromModel(modelDraft);
            setModelPreviewValidationState('checking', 'Validating live JSON preview...');

            try {
                const response = await fetchImpl(validationUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: snapshot })
                });
                const result = await response.json();
                if (runId !== previewValidationState.runId) return;

                if (result.valid) {
                    if (result.warning) {
                        setModelPreviewValidationState('valid', `Valid model (${result.warning})`);
                    } else {
                        setModelPreviewValidationState('valid', 'Valid BIDS Stats Model.');
                    }
                } else {
                    const message = result.error ? String(result.error) : 'Schema validation failed.';
                    setModelPreviewValidationState('invalid', message);
                }
            } catch (error) {
                if (runId !== previewValidationState.runId) return;
                setModelPreviewValidationState('error', `Validation request failed: ${error.message}`);
            }
        }

        function updateModelJsonPreview() {
            const preview = getElement('model-json-preview');
            if (!preview) return;

            const modelDraft = getModelDraft();
            if (!modelDraft || typeof modelDraft !== 'object') {
                preview.textContent = 'Load a model to see the live JSON preview.';
                preview.classList.add('model-editor-preview-empty');
                setModelPreviewValidationState('idle', 'Load a model to run live schema validation.');
                return;
            }

            const snapshot = stripLegacyGeneratedColumnsFromModel(modelDraft);
            preview.textContent = JSON.stringify(snapshot, null, 2);
            preview.classList.remove('model-editor-preview-empty');
            scheduleModelPreviewValidation();
        }

        return {
            stripLegacyGeneratedColumnsFromModel,
            updateModelJsonPreview
        };
    }

    window.BidspmAnalysisPreviewValidation = {
        createPreviewController
    };
})();