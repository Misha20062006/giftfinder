import hashlib
from pathlib import Path

import pytest

from giftfinder import updates


def release(version='0.9.0', suffix='Windows-x64-Setup.exe', content=b'installer', **changes):
    tag = 'v' + version + ('-android.1' if suffix.startswith('Android') else '')
    name = 'GiftFinder-' + version + '-' + suffix
    asset = {'name': name, 'browser_download_url': updates.PREFIX + tag + '/' + name,
             'digest': 'sha256:' + hashlib.sha256(content).hexdigest(), 'size': len(content)}
    asset.update(changes)
    return {'tag_name': tag, 'draft': False, 'prerelease': suffix.startswith('Android'), 'assets': [asset]}


@pytest.mark.parametrize('system,machine,format,expected', [
    ('win32','AMD64',None,'Windows-x64-Setup.exe'),
    ('darwin','arm64',None,'macOS-arm64.pkg'),
    ('darwin','x86_64',None,'macOS-x64.pkg'),
    ('linux','x86_64','deb','Linux-x64.deb'),
    ('linux','aarch64','rpm','Linux-arm64.rpm'),
    ('android','aarch64',None,'Android-arm64-v8a.apk')])
def test_updates_select_the_system_installer(system, machine, format, expected):
    assert updates.target_suffix(system, machine, format) == expected


def test_version_order_platform_and_preview_channel():
    rows = [release('0.9.0'), release('0.10.0'), release('0.11.0', suffix='Android-arm64-v8a.apk')]
    assert updates.select_release(rows, 'Windows-x64-Setup.exe', '0.8.0').version == '0.10.0'
    assert updates.select_release(rows, 'Android-arm64-v8a.apk', '0.8.0').version == '0.11.0'
    assert updates.select_release(rows, 'macOS-arm64.pkg', '0.8.0') is None
    assert updates.select_release(rows, 'Windows-x64-Setup.exe', '0.10.0') is None
    rows[1]['draft'] = True
    rows[0]['prerelease'] = True
    assert updates.select_release(rows, 'Windows-x64-Setup.exe', '0.8.0') is None


@pytest.mark.parametrize('changes', [
    {'browser_download_url':'https://example.com/installer.exe'},
    {'digest':''}, {'digest':'sha256:'+'z'*64}, {'size':-1}, {'size':True}])
def test_invalid_update_metadata_is_rejected(changes):
    with pytest.raises(ValueError):
        updates.select_release([release(**changes)], 'Windows-x64-Setup.exe', '0.8.0')


class Response:
    url = 'https://release-assets.githubusercontent.com/installer'
    def __init__(self, content): self.content = content
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def raise_for_status(self): pass
    def iter_content(self, size): yield self.content


def test_download_verifies_bytes_before_making_installer_available(tmp_path, monkeypatch):
    row = updates.select_release([release()], 'Windows-x64-Setup.exe', '0.8.0')
    monkeypatch.setattr(updates.requests, 'get', lambda *args, **kwargs: Response(b'installer'))
    events = []
    path = updates.download_release(row, tmp_path, events.append)
    assert path.read_bytes() == b'installer' and events == [100]
    assert not list(tmp_path.glob('*.part'))


@pytest.mark.parametrize('content', [b'tampered', b'installer-too-long'])
def test_bad_installer_never_replaces_a_verified_download(tmp_path, monkeypatch, content):
    row = updates.select_release([release()], 'Windows-x64-Setup.exe', '0.8.0')
    existing = tmp_path / row.name
    existing.write_bytes(b'previous verified installer')
    monkeypatch.setattr(updates.requests, 'get', lambda *args, **kwargs: Response(content))
    with pytest.raises(ValueError):
        updates.download_release(row, tmp_path)
    assert existing.read_bytes() == b'previous verified installer'
    assert not list(tmp_path.glob('*.part'))


def test_cancel_during_download_does_not_leave_an_installable_file(tmp_path, monkeypatch):
    row = updates.select_release([release()], 'Windows-x64-Setup.exe', '0.8.0')
    monkeypatch.setattr(updates.requests, 'get', lambda *args, **kwargs: Response(b'installer'))
    with pytest.raises(InterruptedError):
        updates.download_release(row, tmp_path, cancelled=lambda: True)
    assert not list(tmp_path.iterdir())


def test_windows_update_handoff_is_explicit_and_uses_the_verified_path(tmp_path, monkeypatch):
    path = tmp_path / 'GiftFinder setup.exe';path.write_bytes(b'installer')
    calls = []
    monkeypatch.setattr(updates.sys, 'platform', 'win32')
    monkeypatch.setattr(updates.subprocess, 'Popen', lambda args, **kwargs: calls.append((args,kwargs)))
    assert updates.launch_installer(path)
    assert calls == [([str(path), '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/UPDATE'], {'close_fds':True})]
