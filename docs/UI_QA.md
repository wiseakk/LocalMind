# UI verification и ручная визуальная приёмка

Актуальный этап Constellation:28 DOM-проверок и76 локальных/HTTP ресурсов
проверены; браузерная визуальная приёмка остаётся заблокированной. Полный отчёт,
before/after и команды: [CONSTELLATION_UI.md](CONSTELLATION_UI.md).

## Архив предыдущей проверки

В этом запуске реальный браузер не предоставлен CUA. `npx playwright install
chromium` и `npm run test:ui` остановились с `spawn EPERM` до выполнения тестов.
Нет подтверждённых скриншотов и наблюдений реального 100/125/140% zoom.

Действительно выполненные DOM-проверки: `npm run test:dom` — 4 passed.
Они загружают настоящий app.js, DOMPurify и KaTeX в JSDOM. Проверены code/table/
list/math, XSS и media filtering, plain-text fallback, editable transcript без
пузыря/отправки, один запрос при двух submit, ранний status при задержанном
комментарии, single-flight mic startup, recovery после recorder.start exception
и mute во время незавершённого TTS fetch. JSDOM не подтверждает пиксели или звук.

## Повторяемый browser run

После установки dev assets и запуска сервера:

```powershell
npm ci
npx playwright install chromium
npm run test:ui
```

Первичные API для этого набора проверены по
[официальной документации Playwright](https://playwright.dev/docs/test-use-options).
Семь тестов находятся в `tests/browser/ui.spec.mjs`; не заявляйте их пройденными
до фактического запуска. `test-results/` содержит скриншоты после успешного прогона.
Тесты использует isolated browser context; часть API mock, lamp smoke — реальный
DEMO endpoint с отключённой генерацией. Внешние интернет-ресурсы не нужны.

## Ручной checklist (статус каждого пункта пока «не проверено»)

- Desktop 1440×1000: 100%, 125%, 140% browser zoom; видны поле, send, mic,
  raw transcript, статус действия и технический журнал; нет горизонтального overflow.
- 390×844 и tablet: sidebar открывается и закрывается; скрытая панель inert и
  не перехватывает Tab; composer доступен при длинной истории и голосовом draft.
- Tab/Shift+Tab/Enter/Escape: виден focus, native dialog удерживает фокус и
  возвращает его вызывающей кнопке; Escape не закрывает боковую панель под dialog.
- `prefers-reduced-motion: reduce`: нет pulse/entrance/hover motion, чтение доступно.
- Реальная последовательность: ready → pending → deterministic chip → commentary;
  stop Ollama после действия не удаляет chip и не повторяет выполнение.
- Mic: разрешение/отказ, двойной клик до получения разрешения, запись, stop,
  авто-stop30s, processing, silence/corrupt, editable draft, correction, явная отправка.
- Страницу покинуть во время записи/ожидания TTS: tracks остановлены, новое
  воспроизведение не начинается; возврат страницы не оставляет controls disabled.
- Play/stop/mute Piper: слышен русский голос, отказ действия озвучивается отказом;
  uninstalled voice показывает инструкцию, браузерный сетевой голос не подставляется.
- Markdown: fenced code и tildes, таблица/списки/heading, `\(...\)`, `\[...\]`,
  `$$...$$`; `$5 и $10` обычный текст. Script/event-handler не исполняются,
  внешние картинки не делают запросов, local font resources доступны без сети.
- Permission picker: unknown/ambiguous отказ, точная выбранная запись работает
  после разрешения, изменение цели отзывает право, перезапуск сбрасывает все права.

Записывайте браузер/версию, zoom, размер окна, пройденные пункты и дефекты.
Настоящий browser zoom и CSS zoom в automated screenshot — разные проверки;
оба полезны, один не следует выдавать за другой.

## Constellation current run — 2026-10-28

The preceding notes describe earlier UI runs. Current implementation, actual
28 DOM checks,76 local/HTTP asset checks, before/after report, commands and
browser/hardware blockers are documented in [CONSTELLATION_UI.md](CONSTELLATION_UI.md).
Browser coverage is now in ui.spec.mjs and constellation.spec.mjs. Every
non-origin HTTP(S) request is actively blocked before navigation. Real browser
execution is still blocked by process/IPC permissions; no screenshot or visual
approval is claimed. CSS scale tests are clearly distinct from actual zoom.
