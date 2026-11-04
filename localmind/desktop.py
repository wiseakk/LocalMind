"""Installed GUI entry point; private CPython runs all worker modules normally."""
import os
import socket
import sys
import threading
from .paths import migrate_legacy, legacy_preferences_plan


def main():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon, QGuiApplication
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .desktop_shell import DesktopWindow, ICON_PATH
    import uvicorn
    # Qt 6 handles Per-Monitor V2 DPI. No extra Windows/CSS scale multiplier.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if os.name == 'nt':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('LocalMind.Desktop.1')
    app = QApplication(sys.argv)
    app.setApplicationName('LocalMind')
    app.setOrganizationName('LocalMind')
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setStyle('Fusion')
    listener = server = thread = window = None
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
                                log_config=None, proxy_headers=False, timeout_graceful_shutdown=3))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        import time
        deadline = time.monotonic() + 20
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.05)
        if not server.started:
            server.should_exit = True
            raise RuntimeError('Не удалось запустить локальный сервер. Восстановите LocalMind установщиком.')
        window = DesktopWindow(settings.port)
        window.show()
        window.load_ui()
        return app.exec()
    except Exception:
        # Raw socket/Chromium tracebacks may contain URLs and personal paths.
        QMessageBox.critical(None, 'LocalMind — восстановление',
            'Не удалось запустить LocalMind. Закройте предыдущий экземпляр и повторите попытку. '
            'Если ошибка сохраняется, восстановите приложение установщиком. Модели и настройки сохранятся.')
        return 1
    finally:
        if window is not None:
            window.closing = True
            window.theme_timer.stop()
            window.tray.hide()
            # Destroy the renderer before its persistent profile, releasing all
            # microphone handles even when the page or JavaScript has crashed.
            import shiboken6
            shiboken6.delete(window.view)
            shiboken6.delete(window.profile)
        if server is not None:
            server.should_exit = True
        if thread is not None:
            # ASGI lifespan owns STT/TTS workers and waits for their shutdown.
            thread.join()
        if listener is not None:
            listener.close()


if __name__ == '__main__':
    sys.exit(main())
