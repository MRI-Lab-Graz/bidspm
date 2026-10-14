// browse_breadcrumb.js
// Breadcrumb ("Root / part / part") shared by the folder-browser modals of the analysis and transformer builder pages.
(function () {
  'use strict';

  // Fills <ol> for currentPath. Every part but the last links to its folder via navigate(path); the last is the
  // folder being shown. Options: itemClass for the <li> elements, linkClass for the <a> elements.
  function renderBreadcrumb(ol, currentPath, navigate, { itemClass = 'breadcrumb-item', linkClass = '' } = {}) {
    ol.innerHTML = '';

    const link = (text, path) => {
      const a = document.createElement('a');
      a.href = '#';
      if (linkClass) a.className = linkClass;
      a.textContent = text;
      a.addEventListener('click', (event) => {
        event.preventDefault();
        navigate(path);
      });
      return a;
    };

    const root = document.createElement('li');
    root.className = itemClass;
    root.appendChild(link('Root', '/'));
    ol.appendChild(root);

    const parts = String(currentPath || '').split('/').filter(part => part !== '');
    let built = '';
    parts.forEach((part, index) => {
      built += `/${part}`;
      const last = index === parts.length - 1;
      const li = document.createElement('li');
      li.className = itemClass + (last ? ' active' : '');
      if (last) li.textContent = part;
      else li.appendChild(link(part, built));
      ol.appendChild(li);
    });
  }

  window.BIDSPMBrowseBreadcrumb = renderBreadcrumb;
})();
