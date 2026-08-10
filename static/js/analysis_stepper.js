(function () {
    const DISMISSED_KEY = 'bidspm_stepper_dismissed';

    const STEP_HINTS = [
        'Fill in the folder paths: Working Directory, BIDS, Derivatives, fMRIPrep.',
        'Select or create a BIDS Stats Model JSON file for your analysis.',
        'Choose actions (Smooth / Stats / Dataset) and set per-run options.',
        'Review your configuration, then click Save & Run to start the pipeline.',
    ];

    function isStepDone(step) {
        if (step === 1) {
            return ['input-WD','input-BIDS_DIR','input-DERIVATIVES_DIR','input-FMRIPREP_DIR']
                .every(id => (document.getElementById(id)?.value || '').trim() !== '');
        }
        if (step === 2) {
            return (document.getElementById('input-MODELS_FILE')?.value || '').trim() !== '';
        }
        if (step === 3) {
            return Array.from(document.querySelectorAll('input[name="action"]:checked')).length > 0;
        }
        return false;
    }

    function refreshStepper() {
        const steps = document.querySelectorAll('.stepper-step');
        steps.forEach(btn => {
            const s = Number(btn.dataset.step);
            btn.classList.toggle('done', isStepDone(s));
        });
    }

    function activateStep(stepNum) {
        const steps = document.querySelectorAll('.stepper-step');
        steps.forEach(btn => btn.classList.remove('active'));
        const btn = document.querySelector(`.stepper-step[data-step="${stepNum}"]`);
        if (btn) btn.classList.add('active');
        const hintEl = document.getElementById('stepper-hint');
        if (hintEl) hintEl.textContent = STEP_HINTS[stepNum - 1] || '';
    }

    function scrollToTarget(targetId) {
        // Try by id first, then by class
        let el = document.getElementById(targetId);
        if (!el) el = document.querySelector('.' + targetId);
        if (!el) return;
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        // Expand if it's a Bootstrap collapse
        if (el.classList.contains('collapse') && !el.classList.contains('show')) {
            const bsCollapse = bootstrap.Collapse.getOrCreateInstance(el);
            bsCollapse.show();
        }
    }

    function initStepper() {
        const stepper = document.getElementById('analysis-stepper');
        if (!stepper) return;

        // Hide if previously dismissed
        if (localStorage.getItem(DISMISSED_KEY) === '1') {
            stepper.style.display = 'none';
            return;
        }

        // Dismiss button
        document.getElementById('stepper-dismiss')?.addEventListener('click', () => {
            localStorage.setItem(DISMISSED_KEY, '1');
            stepper.style.display = 'none';
        });

        // Step buttons
        document.querySelectorAll('.stepper-step').forEach(btn => {
            btn.addEventListener('click', () => {
                const stepNum = Number(btn.dataset.step);
                const targetId = btn.dataset.target;
                activateStep(stepNum);
                scrollToTarget(targetId);
            });
        });

        refreshStepper();

        // Refresh when inputs change
        document.addEventListener('input', refreshStepper);
        document.addEventListener('change', refreshStepper);
    }

    // Run after DOM is ready (this file loads before inline script)
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initStepper);
    } else {
        initStepper();
    }
})();
