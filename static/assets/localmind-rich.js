/* LocalMind: offline and sanitized Markdown + KaTeX, and truthful friendly action replies. */
(function () {
  'use strict';

  let lastFriendly = -1;
  const confirmations = ['Готово!', 'Есть!', 'Сделано!'];
  function friendlyRuleAnswer(answer, engine) {
    if (engine !== 'rules' || typeof answer !== 'string') return answer;
    // Only celebrate confirmed successes, never a refusal/failed request.
    const isSuccess = /^ДЕМО:\s*.+\s[—-]\s(?:включен[ао]?|выключен[ао]?)[.!]?\s*$/i.test(answer)
      || /^Запущено приложение:\s*[^\r\n]+[.]?$/i.test(answer);
    if (isSuccess) {
      lastFriendly = (lastFriendly + 1) % confirmations.length;
      return confirmations[lastFriendly] + '\n\n' + answer;
    }
    if (/^Команда содержит отрицание\./i.test(answer)) {
      return 'Понял, ничего не трогаю.\n\n' + answer;
    }
    return answer;
  }

  function hideMathInMarkdown(text) {
    const math = [];
    // Keep fenced/inline code untouched before extracting math.
    const protectedCode = /(```[\s\S]*?```|`[^`\n]*`)/g;
    const segments = text.split(protectedCode);
    const mathPattern = /\\\[[\s\S]*?\\\]|\$\$[\s\S]*?\$\$|\\\([\s\S]*?\\\)|(?<!\\)\$([^\r\n$]+?)\$/g;
    return {
      markup: segments.map((segment, index) => {
        if (index % 2 === 1) return segment;
        return segment.replace(mathPattern, (raw) => {
          const display = raw.startsWith('\\[') || raw.startsWith('$$');
          const tex = raw.slice(2, -2).trim();
          const inlineTex = raw.startsWith('$') && !raw.startsWith('$$');
          const expression = inlineTex ? raw.slice(1, -1).trim() : tex;
          const id = math.length;
          math.push({ expression, display });
          return `LOCALMINDMATH${id}TOKEN`;
        });
      }).join(''),
      math,
    };
  }

  function renderLocalMindMessage(target, raw) {
    const text = String(raw ?? '');
    const parser = window.marked;
    const purifier = window.DOMPurify;
    const mathEngine = window.katex;
    if (!parser?.parse || !purifier?.sanitize || !mathEngine?.render) {
      target.textContent = text; // Fail safe: never display untrusted HTML without sanitizer.
      return;
    }
    try {
      const prepared = hideMathInMarkdown(text);
      const html = parser.parse(prepared.markup, { gfm: true, breaks: true });
      target.innerHTML = purifier.sanitize(html, {
        USE_PROFILES: { html: true },
        FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form'],
        FORBID_ATTR: ['style'],
        ALLOW_DATA_ATTR: false,
      });
      for (const a of target.querySelectorAll('a[href]')) {
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
      }
      const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
      const nodes = [];
      while (walker.nextNode()) {
        const n = walker.currentNode;
        if (!n.parentElement?.closest('pre, code, kbd, samp, a')) nodes.push(n);
      }
      const placeholder = /LOCALMINDMATH(\d+)TOKEN/g;
      for (const textNode of nodes) {
        const value = textNode.nodeValue;
        placeholder.lastIndex = 0;
        if (!placeholder.test(value)) continue;
        placeholder.lastIndex = 0;
        const fragment = document.createDocumentFragment();
        let previous = 0;
        for (const match of value.matchAll(placeholder)) {
          fragment.append(document.createTextNode(value.slice(previous, match.index)));
          const item = prepared.math[Number(match[1])];
          if (item) {
            const span = document.createElement('span');
            try {
              mathEngine.render(item.expression, span, {
                displayMode: item.display,
                throwOnError: false,
                trust: false,
                maxExpand: 1000,
                maxSize: 10,
              });
            } catch (_error) {
              span.textContent = item.expression;
            }
            fragment.append(span);
          } else {
            fragment.append(document.createTextNode(match[0]));
          }
          previous = match.index + match[0].length;
        }
        fragment.append(document.createTextNode(value.slice(previous)));
        textNode.replaceWith(fragment);
      }
    } catch (error) {
      console.warn('[LocalMind] Rich text rendering failed; plain text fallback', error);
      target.textContent = text;
    }
  }

  window.friendlyRuleAnswer = friendlyRuleAnswer;
  window.renderLocalMindMessage = renderLocalMindMessage;
}());
