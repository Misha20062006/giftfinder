import ast
import configparser
import io
from pathlib import Path
import tarfile
import zipfile

import pytest

from tools import build_android


def test_modern_sdk_compatibility_adds_only_a_missing_legacy_command(tmp_path):
    manager = tmp_path / 'cmdline-tools/latest/bin/sdkmanager'
    manager.parent.mkdir(parents=True)
    manager.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
    build_android.ensure_sdk_compatibility(tmp_path)
    wrapper = tmp_path / 'tools/bin/sdkmanager'
    assert wrapper.is_file()
    assert str(manager) in wrapper.read_text(encoding='utf-8')
    wrapper.write_text('existing sdk command', encoding='utf-8')
    build_android.ensure_sdk_compatibility(tmp_path)
    assert wrapper.read_text(encoding='utf-8') == 'existing sdk command'


def test_staging_uses_tracked_allowlist_and_keeps_future_import_valid(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    files = {
        'giftfinder/mobile_ui.py': 'def main(): pass\n',
        'giftfinder/catalog_full.json': '{}',
        'third-party/NOTICE': 'Third-party terms',
        'UNLICENSE': 'Original code license',
        'mobile/main.py': '"""Entrypoint."""\nfrom __future__ import annotations\nprint("ready")\n',
        'profile/preferences.json': 'must not ship',
        '.env': 'must not ship',
        'tests/test_example.py': 'must not ship',
    }
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')
    monkeypatch.setattr(build_android, 'ROOT', root)
    monkeypatch.setattr(build_android, 'run', lambda *a, **k: '\0'.join(files) + '\0')
    target = tmp_path / 'stage'
    target.mkdir()
    build_android.stage_project(target, smoke=True)
    source = (target / 'main.py').read_text(encoding='utf-8')
    ast.parse(source)
    assert "GIFT_FINDER_ANDROID_SMOKE" in source
    assert (target / 'third-party/NOTICE').is_file()
    assert not (target / 'profile').exists()
    assert not (target / '.env').exists()
    assert not (target / 'tests').exists()


def test_buildozer_patch_preserves_official_qt_recipe_and_includes_runtime(tmp_path):
    (tmp_path / 'buildozer.spec').write_text(
        '[app]\np4a.bootstrap = qt\np4a.local_recipes = /official/recipes\n'
        'p4a.commit = pinned\nandroid.permissions = ACCESS_NETWORK_STATE\n[buildozer]\nbin_dir = bin\n', encoding='utf-8')
    build_android.patch_buildozer(tmp_path, tmp_path / 'bin', '0.7.0', 'arm64-v8a')
    config = configparser.ConfigParser(interpolation=None)
    config.read(tmp_path / 'buildozer.spec', encoding='utf-8')
    app = config['app']
    assert app['p4a.local_recipes'] == '/official/recipes'
    assert app['p4a.commit'] == 'pinned'
    assert app['requirements'].startswith('python3,sqlite3,openssl,shiboken6,PySide6,')
    assert 'requests==' in app['requirements'] and 'beautifulsoup4==' in app['requirements']
    assert all(ext in app['source.include_exts'].split(',') for ext in ('json', 'png', 'svg', 'pem'))
    assert set(app['android.permissions'].split(',')) == {'INTERNET', 'ACCESS_NETWORK_STATE'}
    assert app['package.domain'] + '.' + app['package.name'] == build_android.PACKAGE_ID
    assert app['android.release_artifact'] == 'apk'
    assert app['android.numeric_version'] == '70000'


def test_compilers_never_receive_signing_secrets(monkeypatch):
    for name in ('ANDROID_KEYSTORE_BASE64', 'ANDROID_KEYSTORE_PASSWORD',
                 'ANDROID_KEY_PASSWORD', 'ANDROID_KEY_ALIAS', 'GIFT_FINDER_ANDROID_KEYSTORE'):
        monkeypatch.setenv(name, 'test-only-placeholder')
    monkeypatch.setenv('ANDROID_HOME', '/sdk')
    environment = build_android.compilation_environment()
    assert not any(name.startswith('ANDROID_KEY') for name in environment)
    assert 'GIFT_FINDER_ANDROID_KEYSTORE' not in environment
    assert environment['ANDROID_HOME'] == '/sdk'


def fake_apk(path, *, omit=None):
    names = ['giftfinder/catalog_full.json', 'giftfinder/monochrome_pairs.json',
             'giftfinder/rates_seed.json', 'giftfinder/themes_curated.json',
             'requests/__init__.py', 'bs4/__init__.py', 'certifi/cacert.pem',
             'lib-dynload/_sqlite3.so', 'lib-dynload/_ssl.so']
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name in names:
            if omit and omit in name:
                continue
            info = tarfile.TarInfo(name)
            info.size = 2
            archive.addfile(info, io.BytesIO(b'{}'))
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('assets/private.tar', buffer.getvalue())
        archive.writestr('lib/arm64-v8a/libQt6Core_arm64-v8a.so', b'placeholder')


def test_apk_validation_reads_packaged_resources_without_extracting(tmp_path):
    apk = tmp_path / 'app.apk'
    fake_apk(apk)
    assert build_android.inspect_apk(apk, 'arm64-v8a')['resources_and_dependencies_present']
    fake_apk(apk, omit='cacert.pem')
    with pytest.raises(RuntimeError, match='missing'):
        build_android.inspect_apk(apk, 'arm64-v8a')
