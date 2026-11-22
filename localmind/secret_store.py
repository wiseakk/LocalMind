"""User-scoped DPAPI or Linux Secret Service, with no plaintext fallback."""
import base64
import ctypes
from ctypes import wintypes as w
import os
import re
import subprocess
import sys
import uuid


class Blob(ctypes.Structure):
    _fields_ = [('size', w.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _convert(data, decrypt):
    if os.name != 'nt':
        raise OSError('Безопасное хранение токена поддерживается только Windows DPAPI.')
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    if decrypt:
        function = crypt.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, w.DWORD, ctypes.POINTER(Blob)]
        ok = function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        function = crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), w.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, w.DWORD, ctypes.POINTER(Blob)]
        ok = function(ctypes.byref(source), 'LocalMind Home Assistant', None, None, None, 1, ctypes.byref(result))
    if not ok:
        raise OSError('Windows не разрешила безопасное хранение токена. Подключите контроллер повторно.')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


def protect(token):
    if sys.platform == 'linux':
        reference = 'secret-service:' + uuid.uuid4().hex
        _secret_tool('store', reference, token.encode('utf-8'))
        return reference
    return base64.b64encode(_convert(token.encode('utf-8'), False)).decode('ascii')


def unprotect(ciphertext):
    if sys.platform == 'linux':
        return _secret_tool('lookup', ciphertext).decode('utf-8').rstrip('\n')
    return _convert(base64.b64decode(ciphertext, validate=True), True).decode('utf-8')


def release(reference):
    if sys.platform == 'linux' and isinstance(reference, str) and reference.startswith('secret-service:'):
        try:
            _secret_tool('clear', reference)
        except OSError:
            pass  # The profile may already be disconnected or the keyring locked.


def _secret_tool(operation, reference, secret=None):
    from hashlib import sha256
    from .paths import DATA_ROOT
    if not isinstance(reference, str) or not re.fullmatch(r'secret-service:[0-9a-f]{32}', reference):
        raise OSError('Ссылка на токен в Secret Service недействительна.')
    scope = sha256(os.fsencode(DATA_ROOT)).hexdigest()
    arguments = ['/usr/bin/secret-tool', operation]
    if operation == 'store':
        arguments.append('--label=LocalMind Home Assistant')
    arguments.extend(('application', 'localmind', 'profile', scope, 'credential', reference))
    try:
        result = subprocess.run(arguments, input=secret if secret is not None else b'',
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8, check=True)
        if operation == 'lookup' and not 10 <= len(result.stdout) <= 4097:
            raise OSError('Токен в Secret Service недоступен.')
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise OSError('Разблокируйте Secret Service в текущей сессии Linux и повторите операцию.') from None
