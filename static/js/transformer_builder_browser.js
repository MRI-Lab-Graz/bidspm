(function () {
  'use strict';

  function createTransformerBuilderBrowser(config) {
    const {
      setStatus,
      scanEvents,
      escHtml,
      clearCurrentPreviewFile,
    } = config || {};

    if (typeof setStatus !== 'function' ||
        typeof scanEvents !== 'function' ||
        typeof escHtml !== 'function' ||
        typeof clearCurrentPreviewFile !== 'function') {
      throw new Error('Transformer Builder browser dependencies are incomplete.');
    }

    let tbBrowseModal = null;
    let tbBrowsingPath = '/';
    let evBrowseModal = null;
    let evBrowsingPath = '/';
    let evSelectedFile = '';

    function setSelectedEventFile(path) {
      evSelectedFile = String(path || '').trim();
      const selectedPath = document.getElementById('ev-selected-path');
      if (!selectedPath) return;

      if (evSelectedFile) {
        selectedPath.textContent = evSelectedFile;
        selectedPath.classList.remove('text-danger');
        selectedPath.classList.add('text-muted');
      } else {
        selectedPath.textContent = 'No file selected';
        selectedPath.classList.remove('text-danger');
        selectedPath.classList.add('text-muted');
      }
    }

    function showMissingEventSelection() {
      const selectedPath = document.getElementById('ev-selected-path');
      if (!selectedPath) return;
      selectedPath.textContent = 'Select an events.tsv file first';
      selectedPath.classList.remove('text-muted');
      selectedPath.classList.add('text-danger');
    }

    async function openBidsBrowser() {
      const startPath = document.getElementById('input-bids-dir').value.trim() || '/';
      await fetchBrowse(startPath);
      if (!tbBrowseModal) {
        tbBrowseModal = new bootstrap.Modal(document.getElementById('tb-browse-modal'));
      }
      tbBrowseModal.show();
    }

    async function openEventsBrowser() {
      const fileInput = document.getElementById('input-events-file').value.trim();
      const startPath = fileInput || document.getElementById('input-bids-dir').value.trim() || '/';
      await fetchEventsBrowse(startPath);
      if (!evBrowseModal) {
        evBrowseModal = new bootstrap.Modal(document.getElementById('ev-browse-modal'));
      }
      evBrowseModal.show();
    }

    function applySelectedBidsPath() {
      document.getElementById('input-bids-dir').value = tbBrowsingPath;
      if (tbBrowseModal) tbBrowseModal.hide();
    }

    function applySelectedEventsFile() {
      if (!evSelectedFile) {
        showMissingEventSelection();
        return;
      }

      document.getElementById('input-events-file').value = evSelectedFile;
      clearCurrentPreviewFile();
      if (evBrowseModal) evBrowseModal.hide();
      setStatus('Single events file selected. Click Scan Events to load it.', 'success');
      scanEvents(false);
    }

    async function fetchEventsBrowse(path) {
      try {
        const response = await fetch(`/browse?path=${encodeURIComponent(path)}&extensions=.tsv`);
        const data = await response.json();
        const list = document.getElementById('ev-browse-list');
        if (data.error) {
          list.innerHTML = `<div class="alert alert-danger py-2 px-3 small mb-0">${escHtml(data.error)}</div>`;
          return;
        }

        const breadcrumb = document.getElementById('ev-breadcrumb');
        breadcrumb.innerHTML = '';
        const parts = data.current_path.split('/').filter(Boolean);
        const rootLi = document.createElement('li');
        rootLi.className = 'breadcrumb-item';
        rootLi.innerHTML = '<a href="#" class="text-decoration-none">Root</a>';
        rootLi.querySelector('a').addEventListener('click', event => {
          event.preventDefault();
          fetchEventsBrowse('/');
        });
        breadcrumb.appendChild(rootLi);

        let built = '';
        parts.forEach((part, index) => {
          built += '/' + part;
          const li = document.createElement('li');
          li.className = 'breadcrumb-item' + (index === parts.length - 1 ? ' active' : '');
          const captured = built;
          if (index === parts.length - 1) {
            li.textContent = part;
          } else {
            li.innerHTML = `<a href="#" class="text-decoration-none">${escHtml(part)}</a>`;
            li.querySelector('a').addEventListener('click', event => {
              event.preventDefault();
              fetchEventsBrowse(captured);
            });
          }
          breadcrumb.appendChild(li);
        });

        list.innerHTML = '';
        const dirs = data.items.filter(item => item.type === 'dir');
        const files = data.items.filter(item => item.type === 'file' && item.name.toLowerCase().endsWith('_events.tsv'));

        dirs.forEach(item => {
          const button = document.createElement('button');
          button.className = 'list-group-item list-group-item-action d-flex align-items-center small py-2';
          button.innerHTML = `<i class="fas fa-folder text-warning me-2"></i> ${escHtml(item.name)}`;
          button.addEventListener('click', () => fetchEventsBrowse(item.path));
          list.appendChild(button);
        });

        files.forEach(item => {
          const button = document.createElement('button');
          button.className = 'list-group-item list-group-item-action d-flex align-items-center small py-2';
          button.innerHTML = `<i class="fas fa-file-alt text-primary me-2"></i> ${escHtml(item.name)}`;
          button.addEventListener('click', () => {
            setSelectedEventFile(item.path);
            list.querySelectorAll('.list-group-item').forEach(element => element.classList.remove('active'));
            button.classList.add('active');
          });
          button.addEventListener('dblclick', () => {
            document.getElementById('input-events-file').value = item.path;
            setSelectedEventFile(item.path);
            clearCurrentPreviewFile();
            if (evBrowseModal) evBrowseModal.hide();
            setStatus('Single events file selected. Click Scan Events to load it.', 'success');
            scanEvents(false);
          });
          list.appendChild(button);
        });

        if (!files.length) {
          const msg = document.createElement('div');
          msg.className = 'small text-muted px-3 py-2';
          msg.textContent = 'No *_events.tsv files in this folder.';
          list.appendChild(msg);
        }

        evBrowsingPath = data.current_path;
        if (!evSelectedFile) {
          setSelectedEventFile('');
        }
      } catch (error) {
        document.getElementById('ev-browse-list').innerHTML =
          `<div class="alert alert-danger py-2 px-3 small mb-0">Browse error: ${escHtml(error.message)}</div>`;
      }
    }

    async function fetchBrowse(path) {
      try {
        const response = await fetch(`/browse?path=${encodeURIComponent(path)}&only_dirs=true`);
        const data = await response.json();
        if (data.error) {
          document.getElementById('tb-browse-list').innerHTML =
            `<div class="alert alert-danger py-2 px-3 small mb-0">${escHtml(data.error)}</div>`;
          return;
        }

        const breadcrumb = document.getElementById('tb-breadcrumb');
        breadcrumb.innerHTML = '';
        const parts = data.current_path.split('/').filter(Boolean);
        const rootLi = document.createElement('li');
        rootLi.className = 'breadcrumb-item';
        rootLi.innerHTML = '<a href="#" class="text-decoration-none">Root</a>';
        rootLi.querySelector('a').addEventListener('click', event => {
          event.preventDefault();
          fetchBrowse('/');
        });
        breadcrumb.appendChild(rootLi);

        let built = '';
        parts.forEach((part, index) => {
          built += '/' + part;
          const li = document.createElement('li');
          li.className = 'breadcrumb-item' + (index === parts.length - 1 ? ' active' : '');
          const captured = built;
          if (index === parts.length - 1) {
            li.textContent = part;
          } else {
            li.innerHTML = `<a href="#" class="text-decoration-none">${escHtml(part)}</a>`;
            li.querySelector('a').addEventListener('click', event => {
              event.preventDefault();
              fetchBrowse(captured);
            });
          }
          breadcrumb.appendChild(li);
        });

        const list = document.getElementById('tb-browse-list');
        list.innerHTML = '';
        data.items.filter(item => item.type === 'dir').forEach(item => {
          const button = document.createElement('button');
          button.className = 'list-group-item list-group-item-action d-flex align-items-center small py-2';
          button.innerHTML = `<i class="fas fa-folder text-warning me-2"></i> ${escHtml(item.name)}`;
          button.addEventListener('click', () => fetchBrowse(item.path));
          list.appendChild(button);
        });

        tbBrowsingPath = data.current_path;
        document.getElementById('tb-selected-path').textContent = data.current_path;
      } catch (error) {
        document.getElementById('tb-browse-list').innerHTML =
          `<div class="alert alert-danger py-2 px-3 small mb-0">Browse error: ${escHtml(error.message)}</div>`;
      }
    }

    return Object.freeze({
      applySelectedBidsPath,
      applySelectedEventsFile,
      openBidsBrowser,
      openEventsBrowser,
      setSelectedEventFile,
    });
  }

  window.BIDSPMTransformerBuilderBrowser = createTransformerBuilderBrowser;
})();