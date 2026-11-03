"""Windows user-scoped DPAPI, with no plaintext/token fallback."""
import base64
import ctypes
from ctypes import wintypes as w
import os


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
    return base64.b64encode(_convert(token.encode('utf-8'), False)).decode('ascii')


def unprotect(ciphertext):
    return _convert(base64.b64decode(ciphertext, validate=True), True).decode('utf-8')
