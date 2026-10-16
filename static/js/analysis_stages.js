// Analysis page stages: Folders -> Model -> Options -> Review and run.
// Elements carry data-stage="<name>"; the ones of other stages get .stage-hidden (never removed from the DOM,
// so every id lookup in the other analysis_*.js modules keeps working).
(function () {
    const STAGES = ['folders', 'model', 'options', 'run'];
    const TITLES = {folders: 'Folders', model: 'Model', options: 'Options', run: 'Review and run'};
    const FOLDER_FIELDS = [['input-WD', 'Working Directory'], ['input-BIDS_DIR', 'BIDS Folder'],
                           ['input-DERIVATIVES_DIR', 'Derivatives Folder'], ['input-FMRIPREP_DIR', 'fMRIPrep Folder']];

    const $ = id => document.getElementById(id);
    const val = id => ($(id)?.value || '').trim();
    const baseName = p => p.replace(/[\\/]+$/, '').split(/[\\/]/).pop();
    const actions = () => Array.from(document.querySelectorAll('input[name="action"]:checked')).map(e => e.value);
    const storageKey = () => 'bidspm_stage_' + (typeof currentProjectId !== 'undefined' ? currentProjectId : '');

    function store(name) {
        try { localStorage.setItem(storageKey(), name); } catch (e) { /* storage blocked: the stage just is not remembered */ }
    }
    function stored() {
        try { return localStorage.getItem(storageKey()); } catch (e) { return null; }
    }

    // Why a stage cannot be left yet: {reason, field} or null when it is complete.
    function blocker(name) {
        if (name === 'folders') {
            const missing = FOLDER_FIELDS.find(([id]) => !val(id));
            return missing && {reason: `Set the ${missing[1]} to continue.`, field: $(missing[0])};
        }
        if (name === 'model' && !val('input-MODELS_FILE')) {
            return {reason: 'Choose or create a model file (Models File) to continue.', field: $('input-MODELS_FILE')};
        }
        if (name === 'options' && !actions().length) {
            return {reason: 'Select at least one action to continue.', field: document.querySelector('input[name="action"]')};
        }
        return null;
    }

    function summary(name) {
        if (name === 'folders') {
            return [baseName(val('input-BIDS_DIR')), val('input-SPACE'), val('input-FWHM') && `${val('input-FWHM')} mm`]
                .filter(Boolean).join(' · ');
        }
        if (name === 'model') return baseName(val('input-MODELS_FILE'));
        if (name === 'options') return actions().join(', ');
        return '';
    }

    const index = name => STAGES.indexOf(name);
    const firstIncomplete = () => STAGES.find(s => blocker(s)) || 'run';
    let cur = 'folders';

    function render() {
        const curIdx = index(cur);
        document.querySelectorAll('[data-stage]').forEach(el => el.classList.toggle('stage-hidden', el.dataset.stage !== cur));
        document.querySelectorAll('[data-stage-btn]').forEach(btn => {
            const name = btn.dataset.stageBtn;
            const done = index(name) < curIdx && !blocker(name);
            btn.classList.toggle('current', name === cur);
            btn.classList.toggle('done', done);
            btn.classList.toggle('upcoming', name !== cur && !done);
            if (name === cur) btn.setAttribute('aria-current', 'step'); else btn.removeAttribute('aria-current');
            const line = btn.querySelector('.stage-btn-summary');
            if (line) line.textContent = done ? summary(name) : '';
        });
        $('stage-heading').textContent = `Step ${curIdx + 1} of ${STAGES.length}: ${TITLES[cur]}`;
        const block = blocker(cur);
        $('stage-back').hidden = curIdx === 0;
        $('stage-next').hidden = cur === 'run';
        $('stage-next').setAttribute('aria-disabled', block ? 'true' : 'false');
        $('stage-hint').textContent = block ? block.reason : '';
        renderSummary();
    }

    function renderSummary() {
        const box = $('stage-summary');
        if (!box) return;
        const lines = STAGES.slice(0, 3).map(name => {
            const div = document.createElement('div');
            div.textContent = `${TITLES[name]}: ${summary(name) || 'not set'}`;
            return div;
        });
        box.replaceChildren(...lines);
    }

    function goTo(name, options) {
        if (index(name) < 0) return;
        cur = name;
        store(name);
        render();
        if (options && options.focus) $('stage-heading').focus();
    }

    // Moving forward needs every earlier stage complete; otherwise say why instead of moving.
    function tryGoTo(name) {
        const stuck = STAGES.slice(0, index(name)).find(s => blocker(s));
        if (!stuck) { goTo(name, {focus: true}); return; }
        $('stage-hint').textContent = `Finish "${TITLES[stuck]}" first. ${blocker(stuck).reason}`;
    }

    function onNext() {
        const block = blocker(cur);
        if (!block) { goTo(STAGES[index(cur) + 1], {focus: true}); return; }
        const details = block.field && block.field.closest('details');
        if (details) details.open = true;  // the missing field may sit in a collapsed Advanced block
        if (block.field) block.field.focus();
    }

    function initialStage() {
        const hash = location.hash.match(/^#stage=(\w+)$/);
        if (hash && index(hash[1]) >= 0) return hash[1];
        if (location.hash === '#analysis-model-workspace-section') return 'model';  // back from the transformer builder
        const first = firstIncomplete();
        const last = stored();
        return index(last) >= 0 ? STAGES[Math.min(index(last), index(first))] : first;
    }

    function init() {
        if (!$('analysis-stages')) return;
        document.querySelectorAll('[data-stage-btn]').forEach(btn =>
            btn.addEventListener('click', () => (index(btn.dataset.stageBtn) <= index(cur) ? goTo(btn.dataset.stageBtn, {focus: true}) : tryGoTo(btn.dataset.stageBtn))));
        $('stage-back').addEventListener('click', () => goTo(STAGES[index(cur) - 1], {focus: true}));
        $('stage-next').addEventListener('click', onNext);
        document.addEventListener('input', render);
        document.addEventListener('change', render);
        window.addEventListener('load', render);  // values applied by loadProjectConfig without events
        cur = initialStage();
        render();
    }

    window.analysisStages = {goTo, current: () => cur, isValid: name => !blocker(name)};
    init();
})();
