/* First-party rounded SVG vocabulary; no remote sprite, font icons or HTML input. */
(() => {
  'use strict';
  const paths = {
    plus:'M12 5v14M5 12h14',history:'M3 11a9 9 0 1 1 3 7M3 4v7h7M12 7v5l3 2',image:'M3 4h18v16H3V4Zm0 12 5-5 5 5 3-3 5 5M16 8h.01',wave:'M3 10v4M7 6v12M12 3v18M17 6v12M21 10v4',
    constellation:'M5 6 12 3 19 8 16 18 6 20 5 6 16 18M5 6 19 8M6 20 12 3M19 8 6 20',
    chat:'M7 18 3 21V6a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3H7ZM7 8h10M7 12h6',
    apps:'M4 4h6v6H4ZM14 4h6v6h-6ZM4 14h6v6H4ZM14 14h6v6h-6Z',
    settings:'m9 3-1 3-3 1-2 4 2 2v4l4 3 3-1 3 1 4-3v-4l2-2-2-4-3-1-1-3H9ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
    mic:'M9 6a3 3 0 0 1 6 0v6a3 3 0 0 1-6 0V6ZM5 11v1a7 7 0 0 0 14 0v-1M12 19v3M8 22h8',
    pause:'M8 5v14M16 5v14', stop:'M7 7h10v10H7Z', play:'m8 5 11 7-11 7V5Z',
    menu:'M4 6h16M4 12h16M4 18h16',close:'m6 6 12 12M6 18 18 6',
    attach:'m8 13 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l9-9a2 2 0 0 1 3 3l-9 9',
    arrow:'M5 12h14m-6-6 6 6-6 6',
    center:'M3 8V4a1 1 0 0 1 1-1h4M16 3h4a1 1 0 0 1 1 1v4M21 16v4a1 1 0 0 1-1 1h-4M8 21H4a1 1 0 0 1-1-1v-4M12 8v8M8 12h8',
    move:'M12 3v18M3 12h18m-6-6-3-3-3 3m6 12-3 3-3-3M6 9l-3 3 3 3m12-6 3 3-3 3',
    shield:'m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6l8-3Zm-4 9 3 3 5-6',
    light:'M8 16c0-3-3-3-3-7a7 7 0 0 1 14 0c0 4-3 4-3 7M8 17h8M9 20h6M11 23h2',
    spark:'m12 3 3 6 6 3-6 3-3 6-3-6-6-3 6-3 3-6Z',
    file:'M6 3h8l5 5v13H6V3Zm8 0v6h5M9 13h7M9 17h5'
  };
  function set(el,name) {
    if(!el || !paths[name])return;
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('class','icon');svg.setAttribute('aria-hidden','true');
    const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',paths[name]);svg.append(p);el.replaceChildren(svg);
  }
  window.localmindIcon=set;
  document.querySelectorAll('[data-icon]').forEach(el=>set(el,el.dataset.icon));
})();
