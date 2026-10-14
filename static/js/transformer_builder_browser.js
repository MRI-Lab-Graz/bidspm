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

    function appendBrowseButton(list, iconClass, name, onClick) {
      const button = document.createElement('button');
      button.className = 'list-group-item list-group-item-action d-flex align-items-center small py-2';
      button.innerHTML = `<i class="${iconClass} me-2"></i> ${escHtml(name)}`;
      button.addEventListener('click', onClick);
      list.appendChild(button);
      return button;
    }

    // Fetch /browse for <prefix>-browse-list, draw the breadcrumb and let fill() add the entries.
    async function browseInto(prefix, path, query, fill) {
      const list = document.getElementById(`${prefix}-browse-list`);
      const showError = (message) => {
        list.innerHTML = `<div class="alert alert-danger py-2 px-3 small mb-0">${escHtml(message)}</div>`;
      };
      try {
        const response = await fetch(`/browse?path=${encodeURIComponent(path)}&${query}`);
        const data = await response.json();
        if (data.error) {
          showError(data.error);
          return;
        }

        window.BIDSPMBrowseBreadcrumb(
          document.getElementById(`${prefix}-breadcrumb`),
          data.current_path,
          next => browseInto(prefix, next, query, fill),
          { linkClass: 'text-decoration-none' },
        );
        list.innerHTML = '';
        fill(data, list);
      } catch (error) {
        showError(`Browse error: ${error.message}`);
      }
    }

    function fetchBrowse(path) {
      return browseInto('tb', path, 'only_dirs=true', (data, list) => {
        data.items.filter(item => item.type === 'dir').forEach(item => {
          appendBrowseButton(list, 'fas fa-folder text-warning', item.name, () => fetchBrowse(item.path));
        });
        tbBrowsingPath = data.current_path;
        document.getElementById('tb-selected-path').textContent = data.current_path;
      });
    }

    function fetchEventsBrowse(path) {
      return browseInto('ev', path, 'extensions=.tsv', (data, list) => {
        data.items.filter(item => item.type === 'dir').forEach(item => {
          appendBrowseButton(list, 'fas fa-folder text-warning', item.name, () => fetchEventsBrowse(item.path));
        });

        const files = data.items.filter(item => item.type === 'file' && item.name.toLowerCase().endsWith('_events.tsv'));
        files.forEach(item => {
          const button = appendBrowseButton(list, 'fas fa-file-alt text-primary', item.name, () => {
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
      });
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