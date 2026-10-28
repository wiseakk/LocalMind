"""Exact PDF identity, path boundary and separate read/open consent."""
import os
from unittest.mock import Mock

import pytest

from localmind.file_access import FileAccess, FileAccessError


def pdf(path, text=b'content'):
    path.write_bytes(b'%PDF-1.7\n' + text)
    return path


def granted(tmp_path, opener=None):
    service = FileAccess(lambda: tmp_path, opener or Mock())
    info = service.folder_info()
    service.set_folder_permission(True, info['fingerprint'])
    return service


def test_find_requires_read_grant_and_open_requires_separate_exact_grant(tmp_path):
    path = pdf(tmp_path / 'report.pdf')
    opener = Mock()
    service = FileAccess(lambda: tmp_path, opener)
    assert service.find_latest('conversation').execution_status == 'permission_required'
    service.set_folder_permission(True, service.folder_info()['fingerprint'])
    selected = service.find_latest('conversation')
    assert selected.success and selected.data['path'] == str(path)
    assert selected.data['timestamp_semantics'] == 'last_modified_not_download_time'
    assert not service.open_selected('conversation', selected.resolved_target).success
    opener.assert_not_called()
    service.set_open_permission('conversation', selected.resolved_target, True)
    assert service.open_selected('conversation', selected.resolved_target).execution_status == 'request_accepted'
    opener.assert_called_once_with(path)


def test_latest_modified_deterministic_tie_and_no_recursion(tmp_path):
    for name in ('Z.pdf', 'a.pdf', 'old.pdf'):
        pdf(tmp_path / name)
        os.utime(tmp_path / name, ns=(100, 100 if name == 'old.pdf' else 300))
    nested = tmp_path / 'nested'
    nested.mkdir()
    pdf(nested / 'new.pdf')
    result = granted(tmp_path).find_latest('c')
    assert result.success and result.data['filename'] == 'a.pdf'


def test_file_replacement_revokes_open_and_owner_cannot_be_forged(tmp_path):
    path = pdf(tmp_path / 'selected.pdf', b'first')
    opener = Mock()
    service = granted(tmp_path, opener)
    key = service.find_latest('owner').resolved_target
    with pytest.raises(FileAccessError):
        service.set_open_permission('attacker', key, True)
    service.set_open_permission('owner', key, True)
    stamp = path.stat().st_mtime_ns
    path.unlink()
    pdf(path, b'other')
    os.utime(path, ns=(stamp, stamp))
    assert not service.open_selected('owner', key).success
    opener.assert_not_called()


def test_folder_revocation_stops_previously_granted_file(tmp_path):
    pdf(tmp_path / 'selected.pdf')
    service = granted(tmp_path)
    key = service.find_latest('owner').resolved_target
    service.set_open_permission('owner', key, True)
    service.set_folder_permission(False, '')
    assert not service.open_selected('owner', key).success


def test_disguised_pdf_is_never_openable(tmp_path):
    (tmp_path / 'malware.pdf').write_bytes(b'MZfake')
    result = granted(tmp_path).find_latest('owner')
    assert not result.success


def test_bounded_scan_does_not_claim_newest_on_partial_enumeration(tmp_path, monkeypatch):
    import localmind.file_access as module
    class Rows:
        def __enter__(self):
            class Row:
                name = 'ignore.txt'
            return iter([Row()] * 2049)
        def __exit__(self, *a):
            pass
    monkeypatch.setattr(module.os, 'scandir', lambda p: Rows())
    assert not granted(tmp_path).find_latest('owner').success


def test_folder_identity_fingerprint_prevents_stale_permission(tmp_path):
    service = FileAccess(lambda: tmp_path)
    with pytest.raises(FileAccessError):
        service.set_folder_permission(True, '0' * 64)
    assert not service.folder_info()['allowed']
