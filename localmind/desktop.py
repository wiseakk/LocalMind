"""Qt entry point and lifecycle of the desktop's private loopback listener."""
import errno
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

from .paths import LOGS, atomic_json, legacy_preferences_plan, migrate_legacy

HOST = '127.0.0.1'
START_TIMEOUT = 20
SHUTDOWN_TIMEOUT = 20


def _listen(port):
    listener = socket.socket()
    try:
        if os.name == 'nt':
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((HOST, port))
        listener.listen(128)
        listener.setblocking(False)
    except (OSError, ValueError, OverflowError):
        listener.close()
        raise
    return listener


def _port_accepts(port):
    try:
        with socket.create_connection((HOST, port), timeout=.25):
            return True
    except OSError:
        return False


def _diagnose(stage, error, **details):
    # Never serialize exception messages, local variables, source lines or
    # absolute paths. These can contain settings, tokens and remote URLs.
    number = getattr(error, 'errno', None)
    record = {
        'stage': stage,
        'exception': type(error).__name__,
        'errno': number if type(number) is int else None,
        'traceback': [{'file': Path(frame.filename).name, 'line': frame.lineno}
                      for frame in traceback.extract_tb(error.__traceback__, limit=-12)],
        **details,
    }
    try:
        atomic_json(LOGS / 'desktop-error.json', record)
    except (OSError, ValueError):
        pass
    print(f'LocalMind Desktop: {record}', file=sys.stderr, flush=True)


def _message(stage, error, port):
    if stage == 'listener' and getattr(error, 'errno', None) in (errno.EADDRINUSE, 10048):
        if _port_accepts(port):
            return f'Порт {port} уже принимает локальные соединения. Закройте приложение, которое его использует.'
        return (f'Порт {port} занят на уровне TCP, но слушающий сервер не обнаружен. '
                'Это возможно сразу после закрытия предыдущего соединения. Подождите и повторите запуск.')
    if stage == 'listener':
        return f'Не удалось открыть локальный порт {port}. Проверьте настройки порта.'
    if stage == 'backend_timeout':
        return 'Локальный сервер не успел запуститься. Проверьте журнал Desktop.'
    if stage == 'backend':
        return 'Не удалось запустить локальный сервер LocalMind. Проверьте журнал Desktop.'
    if stage == 'settings':
        return 'Не удалось загрузить настройки LocalMind. Проверьте журнал Desktop.'
    return 'Не удалось открыть окно LocalMind. Проверьте журнал Desktop и графическую сессию.'


def _serve(server, listener, errors):
    try:
        server.run(sockets=[listener])
    except (Exception, SystemExit) as exc:
        errors.append(exc)


def _backend_app(errors):
    async def tracked(scope, receive, send):
        if scope['type'] != 'lifespan':
            from .server import app as api
            await api(scope, receive, send)
            return
        phase = 'startup'
        failed = False

        async def safe_send(message):
            nonlocal phase, failed
            event = message['type']
            if event.endswith('.failed'):
                # Starlette supplies a raw traceback in the message. Uvicorn
                # needs the failure event, while our journal records the cause.
                failed = True
                message = {'type': event}
            await send(message)
            if event == 'lifespan.startup.complete':
                phase = 'shutdown'

        try:
            from .server import app as api
            await api(scope, receive, safe_send)
        except (Exception, SystemExit) as exc:
            errors.append(exc)
            if not failed:
                await safe_send({'type': f'lifespan.{phase}.failed'})

    return tracked


def _stop_backend(server, thread, listener):
    try:
        if server is not None:
            server.should_exit = True
        if thread is not None and thread.ident is not None:
            thread.join(timeout=SHUTDOWN_TIMEOUT)
            if thread.is_alive():
                raise TimeoutError('Backend shutdown exceeded its deadline')
    finally:
        if listener is not None:
            listener.close()


def main():
    app = message_box = listener = server = thread = window = None
    settings = None
    stage = 'qt'
    result = 1
    failure = None
    errors = []
    try:
        from PySide6.QtCore import Qt, QtMsgType, qInstallMessageHandler
        from PySide6.QtGui import QIcon, QGuiApplication
        from PySide6.QtWidgets import QApplication, QMessageBox
        from .desktop_shell import DesktopWindow, ICON_PATH

        # A native Qt fatal error can abort before Python catches an exception.
        def qt_startup_message(kind, context, message):
            if kind == QtMsgType.QtFatalMsg:
                _diagnose('qt_fatal', RuntimeError())
            if previous_handler is not None:
                previous_handler(kind, context, message)

        previous_handler = None
        previous_handler = qInstallMessageHandler(qt_startup_message)
        try:
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
            if os.name == 'nt':
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('LocalMind.Desktop.1')
            app = QApplication(sys.argv)
        finally:
            qInstallMessageHandler(previous_handler)
        message_box = QMessageBox
        app.setApplicationName('LocalMind')
        if sys.platform == 'linux':
            app.setDesktopFileName('localmind')
        app.setOrganizationName('LocalMind')
        app.setWindowIcon(QIcon(str(ICON_PATH)))
        app.setStyle('Fusion')

        stage = 'settings'
        plan = legacy_preferences_plan()
        if plan:
            preview = '\n'.join(row['source'] + '\n→ ' + row['target'] for row in plan)
            if QMessageBox.question(None, 'Перенос настроек',
                    'Найдены старые настройки. Скопировать после просмотра плана?\n'
                    'Существующие данные и исходники сохраняются. Модели переносятся отдельно.\n\n' + preview,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                migrate_legacy(consent=True, reviewed_plan=plan)
        from .settings import settings
        stage = 'listener'
        listener = _listen(settings.port)

        stage = 'backend'
        import uvicorn

        server = uvicorn.Server(uvicorn.Config(_backend_app(errors), host=HOST, port=settings.port,
                                log_config=None, proxy_headers=False, lifespan='on',
                                interface='asgi3', timeout_graceful_shutdown=3))
        thread = threading.Thread(target=_serve, args=(server, listener, errors),
                                  daemon=True, name='LocalMind-Uvicorn')
        thread.start()
        deadline = time.monotonic() + START_TIMEOUT
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.05)
        if not server.started:
            if errors:
                raise errors.pop(0)
            if thread.is_alive():
                stage = 'backend_timeout'
                raise TimeoutError('Backend startup exceeded its deadline')
            raise RuntimeError('Backend exited during startup')
        stage = 'qt'
        window = DesktopWindow(settings.port)
        window.show()
        window.load_ui()
        result = app.exec()
    except (Exception, SystemExit) as exc:
        port = settings.port if settings is not None else None
        failure = (stage, exc, port)
    finally:
        try:
            if window is not None:
                window.closing = True
                window.theme_timer.stop()
                window.tray.hide()
                # Destroy the renderer before its persistent profile.
                import shiboken6
                shiboken6.delete(window.view)
                shiboken6.delete(window.profile)
        except Exception as exc:
            _diagnose('qt_shutdown', exc)
            result = 1
        finally:
            try:
                _stop_backend(server, thread, listener)
            except Exception as exc:
                _diagnose('backend_shutdown', exc)
                result = 1
        if errors and failure is None:
            _diagnose('backend_shutdown', errors[0])
            result = 1
    if failure is not None:
        stage, exc, port = failure
        _diagnose(stage, exc, port=port)
        failure_message = _message(stage, exc, port)
        if message_box is not None:
            message_box.critical(None, 'LocalMind — восстановление', failure_message)
        else:
            print(failure_message, file=sys.stderr)
    return result


if __name__ == '__main__':
    sys.exit(main())
