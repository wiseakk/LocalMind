"""Installed GUI entry point; private CPython runs all worker modules normally."""
import os
import socket
import sys
import threading
from .paths import APP_ROOT, DATA_ROOT, migrate_legacy, legacy_preferences_plan


def main():
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings, QWebEngineProfile
    import uvicorn
    app = QApplication(sys.argv)
    app.setApplicationName('LocalMind')
    try:
        plan = legacy_preferences_plan()
        if plan:
            preview = '\n'.join(row['source'] + '\n→ ' + row['target'] for row in plan)
            if QMessageBox.question(None, 'Перенос настроек',
                    'Найдены старые настройки. Скопировать после просмотра плана?\n'
                    'Существующие данные и исходники сохраняются. Модели переносятся отдельно.\n\n' + preview,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                migrate_legacy(consent=True, reviewed_plan=plan)
        # Load preferences only after the optional reviewed import.
        from .settings import settings
        listener = socket.socket()
        if os.name == 'nt':
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(('127.0.0.1', settings.port))
        listener.listen(128)
        listener.setblocking(False)
        server = uvicorn.Server(uvicorn.Config('localmind.server:app', host='127.0.0.1', port=settings.port,
                                log_config=None, proxy_headers=False))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        import time
        deadline = time.monotonic() + 20
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.05)
        if not server.started:
            server.should_exit = True
            raise RuntimeError('Не удалось запустить локальный сервер. Восстановите LocalMind установщиком.')
        origin = f'http://127.0.0.1:{settings.port}'

        class LocalPage(QWebEnginePage):
            def acceptNavigationRequest(self, url, kind, main_frame):
                return url.scheme() == 'http' and url.host() == '127.0.0.1' and url.port() == settings.port

            def createWindow(self, kind):
                return None

        window = QMainWindow(); window.setWindowTitle('LocalMind'); window.resize(1280, 900)
        view = QWebEngineView(window)
        profile = QWebEngineProfile('LocalMind', view)
        profile.setPersistentStoragePath(str(DATA_ROOT / 'webprofile'))
        profile.setCachePath(str(DATA_ROOT / 'webcache'))
        page = LocalPage(profile, view)
        view.setPage(page)
        view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)

        def permission(url, feature):
            granted = (url.toString().rstrip('/') == origin and feature == QWebEnginePage.Feature.MediaAudioCapture
                       and QMessageBox.question(window, 'Микрофон', 'Разрешить запись по кнопке микрофона?') == QMessageBox.StandardButton.Yes)
            page.setFeaturePermission(url, feature, QWebEnginePage.PermissionPolicy.PermissionGrantedByUser if granted
                                      else QWebEnginePage.PermissionPolicy.PermissionDeniedByUser)
        page.featurePermissionRequested.connect(permission)
        window.setCentralWidget(view); view.load(QUrl(origin)); window.show()
        result = app.exec()
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        return result
    except Exception as exc:
        QMessageBox.critical(None, 'LocalMind — восстановление', str(exc)[:800])
        return 1


if __name__ == '__main__':
    sys.exit(main())
