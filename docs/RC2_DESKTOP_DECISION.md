# RC2 desktop и решение для 1.1

RC2 остаётся на PySide6 6.8.3 / QtWebEngine. Сервер и HTTP API сохраняются.
Системная рамка Windows отвечает за resize, snap, кнопки, Alt+Tab и DPI.
Qt 6 использует логические координаты; ручной коэффициент масштаба Windows,
CSS zoom и frameless hit-testing не добавлены. Геометрия хранится отдельно
от профиля браузера: `config/desktop-window.json` в каталоге данных пользователя.
После отключения монитора обычные границы помещаются в реальную рабочую область.

Один first-party waveform ICO содержит размеры 16–256 px. Его используют
launcher EXE, установщик, ярлыки, окно и трей. Идентификатор ярлыков и Python
окна одинаков: `LocalMind.Desktop.1`. Генератор — `scripts/generate_app_icon.py`.
Трей открывает окно и завершает приложение; крестик завершает приложение.
Тема страницы хранится в `localmind.theme.v1`, оболочка читает только enum
`document.documentElement.dataset.theme`. Произвольного JS-доступа к ОС нет.
Старый профиль `LocalMind` и `webprofile`, ключ `localmind.sttProfile.v1` сохранены.

Загрузка и падение renderer переключают содержимое на native экран восстановления.
Chromium error pages, popup windows, контекстное меню браузера и загрузки браузера
выключены; навигация разрешена только на собственный loopback origin.
Разрешение микрофона спрашивается отдельно, остальные media permissions отклоняются.
Системные ограничения Chromium sandbox не обходятся.

## QML в 1.1

Преимущества Qt Quick: общая native модель фокуса/доступности и тем,
декларативные переходы, меньше зависимости от HTML layout и Chromium lifecycle.
Экономия RAM/startup пока не измерена: Qt Quick также использует GPU, а качество
rich text и доступности зависит от конкретных компонентов.

Стоимость — перенос экранов чата, модели, setup/download/storage/HA, редактируемого
transcript, вложений, истории, Markdown/кода/формул и всех их асинхронных состояний.
Потребуются новый адаптер существующего API, политика безопасного rich text,
проверка клавиатуры/accessibility и повторная продуктовая регрессия вместо DOM тестов.
Это существенно больше доработки оболочки и создаёт риск для демонстрации RC2.

Решение: полную миграцию в RC2 не выполнять. Для 1.1 отдельно согласовать небольшой
QML-прототип чата/настроек с тем же сервером. На одном ПК сравнить запуск, RSS,
resize/DPI 100–200%, клавиатуру, screen reader, Markdown и микрофон. Переходить
только после измеренного выигрыша и достижения функционального паритета.

Первичные API-источники:
[Qt DPI](https://doc.qt.io/qt-6.8/highdpi.html),
[QWidget](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QWidget.html),
[WebEngine settings](https://doc.qt.io/qtforpython-6/PySide6/QtWebEngineCore/QWebEngineSettings.html),
[renderer lifecycle](https://doc.qt.io/qtforpython-6/PySide6/QtWebEngineCore/QWebEnginePage.html),
[Windows DWM](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute).
Это проверка API, а не подтверждение реальной Windows UX-приёмки.
