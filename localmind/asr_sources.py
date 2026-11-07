"""Extra sources for the exact CTranslate2 artifacts pinned in voice_resources.json."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import struct
import time
from urllib.parse import urljoin, urlsplit
import zipfile

from .paths import APP_ROOT, ordinary_tree

MIRRORS = APP_ROOT / 'config/asr_mirrors.json'
DOWNLOAD_API = 'https://cloud-api.yandex.net/v1/disk/public/resources/download'
PUBLIC_HOSTS = {'disk.yandex.ru', 'disk.yandex.com', 'disk.yandex.net', 'yadi.sk'}
DOWNLOAD_HOSTS = {'downloader.disk.yandex.ru', 'downloader.disk.yandex.net',
                  'downloader.disk.yandex.com', 'downloader.dst.yandex.ru'}
CHUNK = 1024 * 1024


class ASRSourceError(ValueError):
    pass


def archive_limit(assets):
    return sum(asset['bytes'] for asset in assets) + CHUNK


def _yandex_url(url, hosts):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.port not in (None, 443)
            or parsed.username is not None or parsed.password is not None or parsed.fragment):
        raise ASRSourceError('Недопустимая HTTPS-ссылка Яндекс Диска.')
    return parsed


def mirror_for(model, assets):
    try:
        path = ordinary_tree(MIRRORS)
        if path.stat().st_size > 16384:
            return None
        row = json.loads(path.read_text(encoding='utf-8')).get(model)
        if not isinstance(row, dict):
            return None
        url, digest, size = row['url'], row['sha256'], row.get('bytes')
        parsed = _yandex_url(url, PUBLIC_HOSTS)
        if (len(url) > 512 or parsed.query or not re.fullmatch(r'/[di]/[A-Za-z0-9_-]+/?', parsed.path)
                or not re.fullmatch(r'[0-9a-fA-F]{64}', digest)
                or size is not None and (type(size) is not int or not 0 < size <= archive_limit(assets))):
            return None
        mirror = {'url': url, 'sha256': digest.lower(), 'bytes': size}
        return {**mirror, 'fingerprint': hashlib.sha256(json.dumps(mirror, sort_keys=True).encode()).hexdigest()}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def check_cancel(cancel):
    if cancel.is_set():
        raise InterruptedError()


def download_archive(client, mirror, target, assets, cancel, progress, register):
    """Resolve the public key through the API, then stream only a Yandex HTTPS file."""
    deadline = time.monotonic() + 15
    with client.stream('GET', DOWNLOAD_API, params={'public_key': mirror['url']},
                       headers={'Accept-Encoding': 'identity'}) as response:
        register(response)
        response.raise_for_status()
        if response.headers.get('content-encoding', 'identity').lower() != 'identity':
            raise ASRSourceError('Некорректное кодирование ответа API Яндекс Диска.')
        body = bytearray()
        for chunk in response.iter_raw():
            check_cancel(cancel)
            body.extend(chunk)
            if len(body) > 16384 or time.monotonic() > deadline:
                raise ASRSourceError('Некорректный ответ API Яндекс Диска.')
    link = json.loads(body)
    if not isinstance(link, dict) or link.get('method') != 'GET' or link.get('templated') is not False:
        raise ASRSourceError('API Яндекс Диска не вернул ссылку на файл.')
    url = link.get('href')
    limit = archive_limit(assets)
    deadline = time.monotonic() + 7200
    for _ in range(4):
        check_cancel(cancel)
        if not isinstance(url, str) or len(url) > 8192:
            raise ASRSourceError('API Яндекс Диска не вернул ссылку на файл.')
        _yandex_url(url, DOWNLOAD_HOSTS)
        with client.stream('GET', url, headers={'Accept-Encoding': 'identity'}) as response:
            register(response)
            if response.is_redirect:
                url = urljoin(url, response.headers.get('location', ''))
                continue
            response.raise_for_status()
            if (response.status_code != 200 or response.headers.get('content-encoding', 'identity').lower() != 'identity'
                    or 'text/html' in response.headers.get('content-type', '').lower()):
                raise ASRSourceError('Яндекс Диск не вернул ZIP-файл.')
            length = response.headers.get('content-length')
            expected = mirror['bytes']
            if length is not None:
                if not length.isdecimal() or not 0 < int(length) <= limit or expected and int(length) != expected:
                    raise ASRSourceError('Размер архива Яндекс Диска не совпадает с конфигурацией.')
                expected = int(length)
            count = 0
            digest = hashlib.sha256()
            progress(0, expected)
            with target.open('xb') as output:
                last_report = time.monotonic()
                for chunk in response.iter_raw():
                    check_cancel(cancel)
                    count += len(chunk)
                    if count > (expected or limit) or time.monotonic() > deadline:
                        raise ASRSourceError('Превышен размер или срок загрузки архива.')
                    digest.update(chunk)
                    output.write(chunk)
                    now = time.monotonic()
                    if now - last_report >= .25:
                        progress(count, expected)
                        last_report = now
            if expected is not None and count != expected:
                raise ASRSourceError('Архив Яндекс Диска получен не полностью.')
            if digest.hexdigest() != mirror['sha256']:
                raise ASRSourceError('SHA-256 архива Яндекс Диска не совпадает.')
            progress(count, expected or count)
            return count
    raise ASRSourceError('Слишком много перенаправлений Яндекс Диска.')


def _check_zip_index(stream, size, count):
    # Standard ZIP only. Bound the central directory before ZipFile allocates it.
    stream.seek(max(0, size - 65557))
    tail = stream.read(65557)
    end = tail.rfind(b'PK\x05\x06')
    if end < 0 or len(tail) - end < 22:
        raise ASRSourceError('ZIP повреждён или имеет неподдерживаемый формат.')
    _, disk, index_disk, disk_count, entries, index_size, offset, comment = struct.unpack_from('<4s4H2LH', tail, end)
    if (disk or index_disk or disk_count != entries or entries > count + 1 or index_size > 16384
            or comment != len(tail) - end - 22 or offset + index_size != size - comment - 22):
        raise ASRSourceError('ZIP содержит недопустимый индекс.')


def _write_asset(source, destination, asset, cancel):
    digest = hashlib.sha256()
    remaining = asset['bytes']
    with destination.open('xb') as output:
        while remaining:
            check_cancel(cancel)
            chunk = source.read(min(remaining, CHUNK))
            if not chunk:
                raise ASRSourceError('Файл Whisper получен не полностью.')
            remaining -= len(chunk)
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != asset['sha256']:
        raise ASRSourceError('Файлы не совпадают с закреплённой версией Whisper. Проверьте профиль и источник.')


def stage_import(incoming, mode, stage, model, assets, cancel):
    size = incoming.stat().st_size
    required = sum(asset['bytes'] for asset in assets)
    if shutil.disk_usage(stage).free < required:
        raise OSError('Недостаточно места')
    names = {Path(asset['path']).name: asset for asset in assets}
    with incoming.open('rb') as stream:
        if mode == 'directory':
            if size != required:
                raise ASRSourceError('Размер выбранных файлов не совпадает с профилем Whisper.')
            for name, asset in names.items():
                _write_asset(stream, stage / name, asset, cancel)
            return
        if not 0 < size <= archive_limit(assets):
            raise ASRSourceError('Размер ZIP выходит за пределы профиля Whisper.')
        _check_zip_index(stream, size, len(names))
        try:
            with zipfile.ZipFile(stream) as archive:
                entries = archive.infolist()
                if len(entries) > len(names) + 1:
                    raise ASRSourceError('В ZIP слишком много записей.')
                files = {}
                prefixes = set()
                folders = set()
                for item in entries:
                    if item.orig_filename != item.filename or item.flag_bits & 1:
                        raise ASRSourceError('ZIP содержит недопустимое имя или шифрование.')
                    mode_bits = stat.S_IFMT(item.external_attr >> 16)
                    if mode_bits not in (0, stat.S_IFREG, stat.S_IFDIR) or item.external_attr & 0x400:
                        raise ASRSourceError('ZIP содержит ссылку или специальный файл.')
                    if item.is_dir() and item.filename == model + '/' and mode_bits != stat.S_IFREG:
                        if item.filename in folders or item.file_size:
                            raise ASRSourceError('ZIP содержит дублирующийся или непустой каталог.')
                        folders.add(item.filename)
                        continue
                    prefix, _, name = item.filename.rpartition('/')
                    if (prefix not in ('', model) or name not in names or name in files
                            or mode_bits == stat.S_IFDIR or item.file_size != names[name]['bytes']
                            or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                        raise ASRSourceError('ZIP содержит недопустимый путь, размер или состав.')
                    files[name] = item
                    prefixes.add(prefix)
                if files.keys() != names.keys() or len(prefixes) != 1 or folders and prefixes != {model}:
                    raise ASRSourceError('В ZIP нужен полный комплект файлов выбранной модели Whisper.')
                for name, asset in names.items():
                    with archive.open(files[name]) as source:
                        _write_asset(source, stage / name, asset, cancel)
                        if source.read(1):
                            raise ASRSourceError('Распакованный файл превышает допустимый размер.')
        except (zipfile.BadZipFile, NotImplementedError, EOFError):
            raise ASRSourceError('ZIP повреждён или имеет неподдерживаемый формат.') from None
