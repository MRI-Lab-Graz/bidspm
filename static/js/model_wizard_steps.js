// model_wizard_steps.js -- the stepper of the model wizard (strip, Next gating, summaries). Classic script loaded
// before model_wizard.js; it uses that file's globals (wiz, $, isComplete, nuisanceChoice) only when called, and
// exposes just window.WizardSteps.
// ---- steps --------------------------------------------------------------------------------------
// Same conventions as the analysis page strip (static/js/analysis_stages.js): done/current/upcoming buttons with a
// one-line summary, aria-current="step", Next with aria-disabled and a visible reason, focus to the heading.
(function () {
const STEPS = ['task', 'recipes', 'nuisance', 'contrasts', 'review'];
    const TITLES = {task: 'Task and conditions', recipes: 'Recipes', nuisance: 'Nuisance regressors', contrasts: 'Contrasts', review: 'Review and save'};
    const stepIndex = (name) => STEPS.indexOf(name);

    // Why a step cannot be left yet, or null.
    const UPDATING = 'Updating the preview\u2026';
    // strict is used when the user tries to move on: the preview must also match the current choices.
    function blocker(name, strict = false) {
        if (!wiz.scan) return wiz.scanError ? 'The study scan failed. Fix the problem or pick another task to continue.' : 'Scanning the study...';
        const boxes = [...$('wiz-conditions').querySelectorAll('input')];
        if ((boxes.length && !boxes.some((b) => b.checked)) || (wiz.preview && !wiz.preview.regressors.length)) {
            return 'No regressor left. Keep at least one condition to continue.';
        }
        if (wiz.buildError) return 'The current choices do not build. See the message above.';
        if (name === 'recipes' && wiz.recipes.some((r) => !isComplete(r))) return 'Finish or remove the incomplete recipe to continue.';
        if (strict && wiz.edit !== wiz.built) return UPDATING;
        return null;
    }

    function summary(name) {
        const n = (k, one, many) => `${k} ${k === 1 ? one : many}`;
        if (name === 'task') return `${$('wiz-task').value} · ${n($('wiz-conditions').querySelectorAll('input:checked').length, 'condition', 'conditions')}`;
        if (name === 'recipes') return wiz.recipes.length ? n(wiz.recipes.length, 'recipe', 'recipes') : 'none';
        if (name === 'nuisance') {
            const v = nuisanceChoice();
            const label = typeof v === 'string' ? v : 'custom';
            return label === 'none' ? 'none' : `${label} (${wiz.preview ? wiz.preview.nuisance.length : '?'})`;
        }
        if (name === 'contrasts') return wiz.preview ? n(wiz.preview.contrasts.length, 'contrast', 'contrasts') : '';
        return '';
    }

    function renderStage() {
        const cur = stepIndex(wiz.step);
        document.querySelectorAll('[data-wiz-step]').forEach((s) => s.classList.toggle('stage-hidden', s.dataset.wizStep !== wiz.step));
        document.querySelectorAll('[data-wiz-btn]').forEach((btn) => {
            const name = btn.dataset.wizBtn;
            const done = stepIndex(name) < cur && !blocker(name);
            btn.classList.toggle('current', name === wiz.step);
            btn.classList.toggle('done', done);
            btn.classList.toggle('upcoming', name !== wiz.step && !done);
            if (name === wiz.step) btn.setAttribute('aria-current', 'step'); else btn.removeAttribute('aria-current');
            btn.querySelector('.stage-btn-summary').textContent = done ? summary(name) : '';
        });
        $('wiz-heading').textContent = `Step ${cur + 1} of ${STEPS.length}: ${TITLES[wiz.step]}`;
        const block = blocker(wiz.step);
        $('wiz-back').hidden = cur === 0;
        $('wiz-next').hidden = cur === STEPS.length - 1;
        $('wiz-next').setAttribute('aria-disabled', block ? 'true' : 'false');
        $('wiz-hint').textContent = block || '';
        updateCheck();
    }

    function goTo(name) {
        wiz.step = name;
        renderStage();
        $('wiz-heading').focus();
    }

    // Forward needs every earlier step complete; otherwise say why instead of moving.
    function tryGoTo(name) {
        const stuck = STEPS.slice(0, stepIndex(name)).find((s) => blocker(s, true));
        if (!stuck) return goTo(name);
        const why = blocker(stuck, true);
        $('wiz-hint').textContent = why === UPDATING ? why : `Finish "${TITLES[stuck]}" first. ${why}`;
    }

    function initStages() {
        document.querySelectorAll('[data-wiz-btn]').forEach((btn) => btn.addEventListener('click', () => {
            const name = btn.dataset.wizBtn;
            if (stepIndex(name) <= stepIndex(wiz.step)) goTo(name); else tryGoTo(name);
        }));
        $('wiz-back').addEventListener('click', () => goTo(STEPS[stepIndex(wiz.step) - 1]));
        $('wiz-next').addEventListener('click', async () => {
            let why = blocker(wiz.step, true);
            if (why === UPDATING) {  // the edit's blur just started a rebuild: wait for it, then move on if it is fine
                $('wiz-hint').textContent = why;
                await whenBuilt();
                why = blocker(wiz.step, true);
            }
            if (!why) goTo(STEPS[stepIndex(wiz.step) + 1]); else $('wiz-hint').textContent = why;
        });
        renderStage();
    }

    window.WizardSteps = {init: initStages, render: renderStage};
})();
