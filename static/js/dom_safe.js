// dom_safe.js: the one helper for text that goes through an HTML template string.
// Dataset names, model entries, typed values and server messages must reach the page as TEXT, never as markup
// (a folder called `<img src=x onerror=...>` would otherwise run script). Prefer textContent / createElement;
// where a template literal is clearer, wrap every non-constant `${}` in escapeHtml(). The guard test
// tests/test_no_unsafe_html_sinks.py fails on an unwrapped interpolation.
(function () {
  'use strict';
  const ENTITIES = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;'};
  window.escapeHtml = (value) => String(value ?? '').replace(/[&<>"'`]/g, (c) => ENTITIES[c]);
})();
