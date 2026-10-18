(function () {
    function createBrowserController(config = {}) {
        const fetchImpl = config.fetchImpl || window.fetch.bind(window);
        const getElement = config.getElement || ((id) => document.getElementById(id));
        const promptImpl = config.promptImpl || window.prompt.bind(window);
        const bootstrapImpl = config.bootstrapImpl || window.bootstrap;
        const modalEl = config.modalEl || getElement('browseModal');
        const getConfigFolderValue = config.getConfigFolderValue || (() => '.');
        const getInputValue = config.getInputValue || (() => '.');
        const setTargetValue = config.setTargetValue || (() => {});

        let currentBrowseTarget = null;
        let currentBrowseScope = 'settings';
        let currentBrowsingPath = '.';

        function renderBrowseError(message) {
            const list = getElement('browse-list');
            if (list) {
                list.innerHTML = `<div class="alert alert-danger py-2 px-3 small mb-0">${escapeHtml(message)}</div>`;
            }
        }

        function renderBrowseBreadcrumb(currentPath, onlyDirs) {
            const breadcrumb = getElement('browse-breadcrumb');
            if (!breadcrumb) return;
            window.BIDSPMBrowseBreadcrumb(breadcrumb, currentPath, (path) => fetchBrowse(path, onlyDirs),
                { itemClass: 'breadcrumb-item x-small' });
        }

        async function fetchBrowse(path, onlyDirs) {
            const response = await fetchImpl(`/browse?path=${encodeURIComponent(path)}&only_dirs=${onlyDirs}`);
            const data = await response.json();
            if (data.error) {
                renderBrowseError(data.error);
                return;
            }

            const list = getElement('browse-list');
            if (!list) return;
            list.innerHTML = '';

            renderBrowseBreadcrumb(data.current_path, onlyDirs);

            (data.items || []).forEach((item) => {
                const button = document.createElement('button');
                button.className = 'list-group-item list-group-item-action d-flex align-items-center small py-2';
                button.innerHTML = `<i class="fas fa-${item.type === 'dir' ? 'folder text-warning' : (item.name.endsWith('.sif') ? 'box text-success' : 'file-code text-primary')} me-2"></i> ${escapeHtml(item.name)}`;
                button.addEventListener('click', () => {
                    if (item.type === 'dir') fetchBrowse(item.path, onlyDirs);
                    else selectPath(item.path);
                });
                list.appendChild(button);
            });

            currentBrowsingPath = data.current_path;
            const selectedPathEl = getElement('selected-browse-path');
            if (selectedPathEl) selectedPathEl.innerText = data.current_path;

            const confirmBtn = getElement('btn-confirm-browse');
            if (confirmBtn) confirmBtn.onclick = () => selectPath(data.current_path);

            const mkdirBtn = getElement('btn-modal-mkdir');
            if (mkdirBtn) {
                mkdirBtn.onclick = async () => {
                    const folderName = promptImpl('Enter new folder name:');
                    if (!folderName) return;

                    const newPath = `${currentBrowsingPath}${currentBrowsingPath.endsWith('/') ? '' : '/'}${folderName}`;
                    try {
                        const mkdirResponse = await fetchImpl('/mkdir', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ path: newPath })
                        });
                        const result = await mkdirResponse.json();
                        if (result.success) {
                            fetchBrowse(currentBrowsingPath, onlyDirs);
                        } else {
                            list.insertAdjacentHTML('afterbegin', `<div class="alert alert-danger py-2 px-3 small mb-1">${escapeHtml(result.error)}</div>`);
                        }
                    } catch (error) {
                        list.insertAdjacentHTML('afterbegin', '<div class="alert alert-danger py-2 px-3 small mb-1">Failed to create folder.</div>');
                    }
                };
            }
        }

        function selectPath(path) {
            if (!currentBrowseTarget) return;
            setTargetValue(currentBrowseTarget, path, currentBrowseScope);
            bootstrapImpl?.Modal?.getInstance(modalEl)?.hide();
        }

        function openBrowser(targetKey, onlyDirs, scope = 'settings') {
            currentBrowseTarget = targetKey;
            currentBrowseScope = scope;

            const startPath = targetKey === 'config-folder'
                ? getConfigFolderValue()
                : getInputValue(targetKey);

            fetchBrowse(startPath || '.', onlyDirs);
            if (modalEl && bootstrapImpl?.Modal) {
                new bootstrapImpl.Modal(modalEl).show();
            }
        }

        return {
            fetchBrowse,
            openBrowser,
            selectPath
        };
    }

    window.BidspmAnalysisBrowser = {
        createBrowserController
    };
})();