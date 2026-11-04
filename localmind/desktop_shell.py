"""Native Windows frame around the existing local UI. No JavaScript OS bridge."""
import os

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QIcon, QPalette
from PySide6.QtWidgets import (QApplication, QLabel, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from .desktop_state import read_state, visible_rect, write_state
from .paths import APP_ROOT, DATA_ROOT, ordinary_tree

ICON_PATH = APP_ROOT / 'static/assets/localmind.ico'


def local_url(url, port):
    return (url.scheme() == 'http' and url.host() == '127.0.0.1'
            and url.port() == port and not url.userName() and not url.password())


class LocalPage(QWebEnginePage):
    def __init__(self, profile, parent, port):
        super().__init__(profile, parent)
        self.port = port

    def acceptNavigationRequest(self, url, kind, main_frame):
        return local_url(url, self.port)

    def createWindow(self, kind):
        return None

    def javaScriptAlert(self, origin, message):
        QMessageBox.information(self.parent(), 'LocalMind', str(message)[:800])


class DesktopWindow(QMainWindow):
    def __init__(self, port, state_path=None):
        super().__init__()
        self.setWindowTitle('LocalMind')
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.state_path = state_path or DATA_ROOT / 'config/desktop-window.json'
        self.saved = read_state(self.state_path)
        self.theme = None
        self.closing = False
        self.origin = QUrl(f'http://127.0.0.1:{port}')
        self.stack = QStackedWidget(self)
        self.setCentralWidget(self.stack)
        self.view = QWebEngineView(self.stack)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.profile = QWebEngineProfile('LocalMind', self)
        self.profile.setPersistentStoragePath(str(ordinary_tree(DATA_ROOT / 'webprofile')))
        self.profile.setCachePath(str(ordinary_tree(DATA_ROOT / 'webcache')))
        self.profile.downloadRequested.connect(lambda download: download.cancel())
        self.page = LocalPage(self.profile, self.view, port)
        self.view.setPage(self.page)
        for attribute in ('LocalContentCanAccessRemoteUrls', 'LocalContentCanAccessFileUrls',
                          'ErrorPageEnabled', 'JavascriptCanOpenWindows', 'FullScreenSupportEnabled',
                          'ScreenCaptureEnabled', 'PluginsEnabled'):
            self.view.settings().setAttribute(getattr(QWebEngineSettings.WebAttribute, attribute), False)
        self.page.featurePermissionRequested.connect(self.permission)
        self.stack.addWidget(self.view)
        self.recovery = QWidget(self.stack)
        layout = QVBoxLayout(self.recovery)
        layout.setContentsMargins(48, 40, 48, 40)
        layout.addStretch()
        self.recovery_title = QLabel('Запускаем LocalMind…', self.recovery)
        self.recovery_title.setStyleSheet('font-size: 24px; font-weight: 600;')
        self.recovery_message = QLabel('Подготавливаем рабочее окно.', self.recovery)
        self.recovery_message.setWordWrap(True)
        self.retry = QPushButton('Повторить', self.recovery)
        self.retry.setMaximumWidth(200)
        self.retry.clicked.connect(self.load_ui)
        self.retry.hide()
        for widget in (self.recovery_title, self.recovery_message, self.retry):
            layout.addWidget(widget)
        layout.addStretch()
        self.stack.addWidget(self.recovery)
        self.stack.setCurrentWidget(self.recovery)
        self.view.loadStarted.connect(self.loading)
        self.view.loadFinished.connect(self.loaded)
        self.page.renderProcessTerminated.connect(lambda *_: self.failed())
        self.load_timeout = QTimer(self)
        self.load_timeout.setSingleShot(True)
        self.load_timeout.timeout.connect(self.failed)
        self.theme_timer = QTimer(self)
        self.theme_timer.setInterval(600)
        self.theme_timer.timeout.connect(self.sync_theme)
        self.theme_timer.start()
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(350)
        self.save_timer.timeout.connect(self.save_preferences)
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip('LocalMind')
        self.tray_menu = QMenu(self)
        open_action = QAction('Открыть', self)
        open_action.triggered.connect(self.open_window)
        exit_action = QAction('Выход', self)
        exit_action.triggered.connect(self.close)
        self.tray_menu.addAction(open_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(exit_action)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self.tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.apply_theme(self.saved.get('theme', 'dark'))
        self.fit_to_screens(self.saved.get('rect'), initial=True)
        if self.saved.get('maximized'):
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        QApplication.instance().screenRemoved.connect(lambda *_: self.fit_to_screens())

    def fit_to_screens(self, rect=None, *, initial=False):
        if rect is None and not initial:
            g = self.normalGeometry()
            rect = (g.x(), g.y(), g.width(), g.height())
        screens = [(g.x(), g.y(), g.width(), g.height())
                   for g in (s.availableGeometry() for s in QApplication.screens())]
        fitted = visible_rect(rect, screens)
        if self.isMaximized():
            self.showNormal()
            self.setGeometry(*fitted)
            self.showMaximized()
        else:
            self.setGeometry(*fitted)

    def open_window(self):
        if self.isMinimized():
            # Preserve maximization when restoring from the tray.
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_window()

    def permission(self, url, feature):
        granted = (local_url(url, self.origin.port()) and url.path() in ('', '/')
                   and feature == QWebEnginePage.Feature.MediaAudioCapture and not self.closing
                   and QMessageBox.question(self, 'Микрофон', 'Разрешить запись по кнопке микрофона?',
                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                       QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes)
        self.page.setFeaturePermission(url, feature,
            QWebEnginePage.PermissionPolicy.PermissionGrantedByUser if granted
            else QWebEnginePage.PermissionPolicy.PermissionDeniedByUser)

    def load_ui(self):
        self.view.load(self.origin)

    def loading(self):
        self.recovery_title.setText('Запускаем LocalMind…')
        self.recovery_message.setText('Подготавливаем рабочее окно.')
        self.retry.hide()
        self.stack.setCurrentWidget(self.recovery)
        self.load_timeout.start(20000)

    def loaded(self, success):
        self.load_timeout.stop()
        if success and local_url(self.page.url(), self.origin.port()):
            self.stack.setCurrentWidget(self.view)
            self.view.setFocus()
            self.sync_theme()
        else:
            self.failed()

    def failed(self):
        if self.closing:
            return
        self.load_timeout.stop()
        self.recovery_title.setText('Не удалось открыть LocalMind')
        self.recovery_message.setText('Повторите попытку. Если ошибка сохраняется, закройте приложение '
                                      'и восстановите его установщиком. Настройки и модели сохранятся.')
        self.retry.show()
        self.stack.setCurrentWidget(self.recovery)

    def sync_theme(self):
        if not self.closing and self.stack.currentWidget() == self.view:
            # One enum read, never a path, URL, command or general native bridge.
            self.page.runJavaScript('document.documentElement.dataset.theme', self.apply_theme)

    def apply_theme(self, theme):
        if self.closing or theme not in ('light', 'dark') or theme == self.theme:
            return
        self.theme = theme
        dark = theme == 'dark'
        background, foreground, field = ('#171a20', '#edf0f7', '#222732') if dark else ('#f5f6fa', '#202633', '#ffffff')
        palette = QPalette()
        for role, color in ((QPalette.ColorRole.Window, background), (QPalette.ColorRole.WindowText, foreground),
                            (QPalette.ColorRole.Base, field), (QPalette.ColorRole.AlternateBase, background),
                            (QPalette.ColorRole.Text, foreground), (QPalette.ColorRole.Button, field),
                            (QPalette.ColorRole.ButtonText, foreground), (QPalette.ColorRole.ToolTipBase, field),
                            (QPalette.ColorRole.ToolTipText, foreground), (QPalette.ColorRole.Highlight, '#586edc'),
                            (QPalette.ColorRole.HighlightedText, '#ffffff')):
            palette.setColor(role, QColor(color))
        QApplication.instance().setPalette(palette)
        self.page.setBackgroundColor(QColor(background))
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            try:
                dwm = ctypes.WinDLL('dwmapi')
                function = dwm.DwmSetWindowAttribute
                function.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
                function.restype = ctypes.c_long
                value = ctypes.c_int(dark)
                function(int(self.winId()), 20, ctypes.byref(value), ctypes.sizeof(value))
            except OSError:
                pass  # Unsupported Windows keeps its system frame.
        self.save_timer.start()

    def save_preferences(self):
        g = self.normalGeometry()
        if g.width() <= 0 or g.height() <= 0:
            return
        try:
            write_state(self.state_path, (g.x(), g.y(), g.width(), g.height()),
                        bool(self.windowState() & Qt.WindowState.WindowMaximized), self.theme)
        except (OSError, ValueError, RuntimeError):
            pass  # A read-only or damaged preferences file must not prevent exit.

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, 'save_timer'):
            self.save_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'save_timer'):
            self.save_timer.start()

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, 'save_timer'):
            self.save_timer.start()

    def closeEvent(self, event):
        self.save_preferences()
        self.closing = True
        self.theme_timer.stop()
        self.load_timeout.stop()
        self.save_timer.stop()
        self.tray.hide()
        self.page.setAudioMuted(True)
        self.view.stop()
        super().closeEvent(event)  # Close means exit, never silently keep recording.
