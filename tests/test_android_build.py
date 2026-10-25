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
        'p4a.commit = pinned\nandroid.permissions = ACCESS_NETWORK_STATE,android.permission.READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE\n[buildozer]\nbin_dir = bin\n', encoding='utf-8')
    build_android.patch_buildozer(tmp_path, tmp_path / 'bin', '0.7.0', 'arm64-v8a')
    config = configparser.ConfigParser(interpolation=None)
    config.read(tmp_path / 'buildozer.spec', encoding='utf-8')
    app = config['app']
    assert app['p4a.local_recipes'] == '/official/recipes'
    assert app['p4a.commit'] == 'pinned'
    assert app['requirements'].startswith('python3,sqlite3,openssl,shiboken6,pyside6,')
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


def test_qt_plugin_selection_accepts_actual_network_manifest_spelling(tmp_path):
    spec = tmp_path / 'pysidedeploy.spec'
    spec.write_text('[qt]\nmodules = Core,Network\n[android]\nplugins = platforms_qtforandroid\n', encoding='utf-8')
    wheel = tmp_path / 'qt.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('PySide6/Qt/lib/Qt6Network_x86_64-android-dependencies.xml',
                         '<rules><bundled file="plugins/tls"/><bundled file="./plugins/networkinformation"/></rules>')
        archive.writestr('PySide6/Qt/plugins/tls/libplugins_tls_qopensslbackend_x86_64.so', b'placeholder')
        archive.writestr('PySide6/Qt/plugins/networkinformation/libplugins_networkinformation_qandroidnetworkinformation_x86_64.so', b'placeholder')
    assert build_android.ensure_declared_qt_plugins(spec, wheel, 'x86_64')
    config = configparser.ConfigParser(interpolation=None)
    config.read(spec, encoding='utf-8')
    assert set(config['android']['plugins'].split(',')) == {
        'platforms_qtforandroid', 'tls_qopensslbackend', 'networkinformation_qandroidnetworkinformation'}
    assert not build_android.ensure_declared_qt_plugins(spec, wheel, 'x86_64')


def test_missing_declared_plugin_is_added_before_apk_alignment_and_signing(tmp_path):
    spec = tmp_path / 'pysidedeploy.spec'
    spec.write_text('[android]\nplugins = tls_qopensslbackend\n', encoding='utf-8')
    wheel = tmp_path / 'qt.whl'
    filename = 'libplugins_tls_qopensslbackend_x86_64.so'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('PySide6/Qt/plugins/tls/' + filename, b'native-qt-plugin')
    apk = tmp_path / 'app.apk'
    with zipfile.ZipFile(apk, 'w') as archive:
        archive.writestr('assets/private.tar', b'original-application')
    assert build_android.include_native_qt_plugins(apk, spec, wheel, 'x86_64') == ['tls_qopensslbackend']
    assert build_android.include_native_qt_plugins(apk, spec, wheel, 'x86_64') == []
    with zipfile.ZipFile(apk) as archive:
        assert archive.read('assets/private.tar') == b'original-application'
        assert archive.getinfo('lib/x86_64/' + filename).compress_type == zipfile.ZIP_STORED


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
        archive.writestr('lib/arm64-v8a/libplugins_tls_qopensslbackend_arm64-v8a.so', b'placeholder')


def test_apk_validation_reads_packaged_resources_without_extracting(tmp_path):
    apk = tmp_path / 'app.apk'
    fake_apk(apk)
    assert build_android.inspect_apk(apk, 'arm64-v8a')['resources_and_dependencies_present']
    fake_apk(apk, omit='cacert.pem')
    with pytest.raises(RuntimeError, match='missing'):
        build_android.inspect_apk(apk, 'arm64-v8a')


def test_actual_manifest_metadata_is_extracted_from_aapt_badging():
    metadata = build_android.manifest_metadata(
        "package: name='org.giftfinder.giftfinder' versionCode='70000' versionName='0.7.0'\n"
        "sdkVersion:'28'\ntargetSdkVersion:'35'\n"
        "uses-permission: name='android.permission.INTERNET'\n"
        "uses-permission: name='android.permission.ACCESS_NETWORK_STATE'\n")
    assert metadata['minimum_android_sdk'] == 28
    assert metadata['target_android_sdk'] == 35
    assert metadata['android_version_code'] == 70000
    assert metadata['android_permissions'] == ['android.permission.ACCESS_NETWORK_STATE', 'android.permission.INTERNET']


def test_only_cached_installer_venv_is_removed_and_compiled_recipes_are_preserved(tmp_path):
    build = tmp_path / 'compilation/android/platform/build-x86_64/build'
    installer = build / 'venv'
    installer.mkdir(parents=True)
    (installer / 'pip-placeholder').write_text('old installer', encoding='utf-8')
    library = build / 'other_builds/openssl/libssl.so'
    library.parent.mkdir(parents=True)
    library.write_bytes(b'compiled-library')
    assert build_android.clear_cached_installer_environment(tmp_path, 'x86_64')
    assert not installer.exists()
    assert library.read_bytes() == b'compiled-library'
    assert not build_android.clear_cached_installer_environment(tmp_path, 'x86_64')
