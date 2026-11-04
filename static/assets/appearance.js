/* Load before styles: only declared appearance values may affect the document. */
(() => {
  'use strict';
  let theme='dark';
  try {
    const saved=localStorage.getItem('localmind.theme.v1');
    if(saved==='light'||saved==='dark')theme=saved;
    else if(window.matchMedia?.('(prefers-color-scheme: light)').matches)theme='light';
  } catch (_) { /* Restricted storage keeps the accessible dark default. */ }
  document.documentElement.dataset.theme=theme;
})();
