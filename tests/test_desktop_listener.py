import asyncio
import errno
import json
import socket
import sys
from unittest.mock import Mock

import pytest

from localmind import desktop


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux TCP TIME_WAIT semantics')
def test_listener_rebinds_while_server_side_connection_is_in_time_wait():
    with desktop._listen(0) as listener:
        port = listener.getsockname()[1]
        with socket.create_connection((desktop.HOST, port), timeout=2) as client:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(2)
                connection.shutdown(socket.SHUT_WR)
                assert client.recv(1) == b''
                client.shutdown(socket.SHUT_WR)
                assert connection.recv(1) == b''

    with socket.socket() as without_reuse:
        with pytest.raises(OSError) as error:
            without_reuse.bind((desktop.HOST, port))
        assert error.value.errno == errno.EADDRINUSE
    with desktop._listen(port) as replacement:
        assert replacement.getsockname()[1] == port


def test_live_listener_remains_exclusive():
    with desktop._listen(0) as listener:
        port = listener.getsockname()[1]
        with pytest.raises(OSError) as error:
            desktop._listen(port)
        if sys.platform != 'win32':
            assert 'уже принимает' in desktop._message('listener', error.value, port)


def test_unreachable_listener_error_is_not_reported_as_running_instance(monkeypatch):
    monkeypatch.setattr(desktop, '_port_accepts', lambda port: False)
    error = OSError(errno.EADDRINUSE, 'sensitive message')
    assert 'слушающий сервер не обнаружен' in desktop._message('listener', error, 8877)
    assert 'локальный сервер' in desktop._message('backend', error, 8877)
    assert 'окно' in desktop._message('qt', error, 8877)


def test_backend_shutdown_timeout_still_closes_listener(monkeypatch):
    monkeypatch.setattr(desktop, 'SHUTDOWN_TIMEOUT', .01)
    thread = Mock(ident=1)
    thread.is_alive.return_value = True
    server, listener = Mock(should_exit=False), Mock()
    with pytest.raises(TimeoutError):
        desktop._stop_backend(server, thread, listener)
    assert server.should_exit
    thread.join.assert_called_once_with(timeout=.01)
    listener.close.assert_called_once()


def test_lifespan_failure_is_recorded_without_raw_traceback(monkeypatch, tmp_path, capsys):
    from localmind import server

    async def bad_app(scope, receive, send):
        await send({'type': 'lifespan.startup.failed', 'message': 'raw-secret-token xyz'})
        raise OSError(errno.EACCES, 'raw-secret-token xyz')

    async def probe():
        events = []
        errors = []

        async def send(event):
            events.append(event)

        await desktop._backend_app(errors)({'type': 'lifespan'}, None, send)
        assert events == [{'type': 'lifespan.startup.failed'}]
        assert len(errors) == 1
        desktop._diagnose('backend', errors[0])

    monkeypatch.setattr(server, 'app', bad_app)
    monkeypatch.setattr(desktop, 'LOGS', tmp_path)
    asyncio.run(probe())
    diagnostics = (tmp_path / 'desktop-error.json').read_text()
    assert 'raw-secret-token' not in diagnostics + capsys.readouterr().err
    record = json.loads(diagnostics)
    assert (record['stage'], record['exception'], record['errno']) == ('backend', 'PermissionError', errno.EACCES)
    assert record['traceback'][-1]['file'] == 'test_desktop_listener.py'
