"""Build a signed Android APK with the official Qt for Python Android recipes.

Run on Linux/macOS with JDK 17, Android SDK 35 and NDK 28c. Credentials are read
only from the environment; generated projects, wheels and profiles stay in build/.
"""
from __future__ import annotations

import argparse
import ast
import configparser
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
QT_VERSION = '6.12.0'
PACKAGE_ID = 'org.giftfinder.giftfinder'
NDK_VERSION = '28.2.13676358'
ARCHITECTURES = {'arm64-v8a': 'aarch64', 'x86_64': 'x86_64'}
PURE_REQUIREMENTS = (
    'requests==2.34.2', 'beautifulsoup4==4.15.0', 'urllib3==2.8.0',
    'certifi==2026.10.23', 'idna==3.20', 'charset-normalizer==3.5.2',
    'soupsieve==3.0.4', 'typing_extensions==4.16.0',
)


def compilation_environment():
    """Build tools sometimes print their environment; never give them signing secrets."""
    environment = os.environ.copy()
    for key in ('ANDROID_KEYSTORE_BASE64', 'ANDROID_KEYSTORE_PASSWORD',
                'ANDROID_KEY_PASSWORD', 'ANDROID_KEY_ALIAS', 'GIFT_FINDER_ANDROID_KEYSTORE'):
        environment.pop(key, None)
    environment['CHARSET_NORMALIZER_USE_MYPYC'] = '0'
    return environment


def run(command, *, cwd=ROOT, capture=False, env=None, timeout=None):
    # No command accepts a password or a token in its argument list.
    print('+', ' '.join(map(str, command)), flush=True)
    result = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                            text=True, check=True, capture_output=capture, timeout=timeout)
    return result.stdout if capture else ''


def version():
    tree = ast.parse((ROOT / 'giftfinder/__init__.py').read_text(encoding='utf-8-sig'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__' for t in node.targets):
            value = ast.literal_eval(node.value)
            if re.fullmatch(r'\d+\.\d+\.\d+', value):
                return value
    raise RuntimeError('Cannot determine GiftFinder version')


def stage_project(destination, *, smoke=False):
    """Copy only tracked application files and third-party notices, never profiles."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / '.giftfinder-source-manifest.json'
    tracked = run(['git', 'ls-files', '-z'], capture=True).split('\0')
    allowed = [name for name in tracked if name and (
        name.startswith(('giftfinder/', 'third-party/')) or
        name in {'UNLICENSE', 'THIRD_PARTY_NOTICES.txt', 'mobile/main.py'})]
    current = {'main.py' if name == 'mobile/main.py' else name for name in allowed}
    previous = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else []
    for name in set(previous) - current:
        stale = destination / name
        if not stale.resolve().is_relative_to(destination) or stale.is_symlink():
            raise RuntimeError('Invalid path in the managed Android staging manifest')
        if stale.is_file():
            stale.unlink()
    for name in allowed:
        source = ROOT / name
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f'Non-regular tracked application file: {name}')
        target = destination / ('main.py' if name == 'mobile/main.py' else name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    main = destination / 'main.py'
    if not main.exists() or not (destination / 'giftfinder/mobile_ui.py').exists():
        raise RuntimeError('The mobile entry point and UI must be tracked before building')
    if smoke:
        # Only the separately labelled x86_64 emulator artifact is offline.
        source = main.read_text(encoding='utf-8-sig')
        tree = ast.parse(source)
        after = 0
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                after = node.end_lineno
            elif isinstance(node, ast.ImportFrom) and node.module == '__future__':
                after = node.end_lineno
            else:
                break
        lines = source.splitlines(keepends=True)
        lines[after:after] = ["import os\nos.environ['GIFT_FINDER_ANDROID_SMOKE'] = '1'\n"]
        main.write_text(''.join(lines), encoding='utf-8')
    manifest_path.write_text(json.dumps(sorted(current), indent=2) + '\n', encoding='utf-8')
    return allowed


def download_wheel(component, architecture, cache):
    name = f'{component}-{QT_VERSION}-{QT_VERSION}-cp310-abi3-android_{architecture}.whl'
    url = f'https://download.qt.io/official_releases/QtForPython/{component}/{name}'
    with urllib.request.urlopen(url + '.sha256', timeout=60) as response:
        expected = response.read().decode('ascii').split()[0].lower()
    if not re.fullmatch('[0-9a-f]{64}', expected):
        raise RuntimeError(f'Invalid official checksum for {component}')
    target = cache / name
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        return target
    temporary = target.with_suffix('.part')
    print(f'Downloading official {component} {architecture} wheel', flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as output:
        shutil.copyfileobj(response, output)
    if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f'Official checksum mismatch: {component}')
    temporary.replace(target)
    return target


def ensure_sdk_compatibility(sdk):
    """Bridge Buildozer's legacy tools/bin path to a modern Android SDK layout."""
    sdk = sdk.resolve()
    legacy = sdk / 'tools/bin/sdkmanager'
    if legacy.is_file():
        return
    modern = sdk / 'cmdline-tools/latest/bin/sdkmanager'
    if not modern.is_file():
        modern = sdk / 'cmdline-tools/bin/sdkmanager'
    if not modern.is_file():
        raise RuntimeError('No modern Android SDK sdkmanager was found')
    if legacy.exists() or legacy.is_symlink() or not legacy.parent.resolve().is_relative_to(sdk):
        raise RuntimeError('Cannot safely create the legacy Android SDK command wrapper')
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('#!/bin/sh\nexec ' + shlex.quote(str(modern)) + ' "$@"\n', encoding='utf-8')
    legacy.chmod(0o755)


def clear_cached_installer_environment(base, architecture):
    """Regenerate p4a's disposable pip venv, preserving every compiled recipe."""
    if architecture not in ARCHITECTURES:
        raise RuntimeError('Unknown Android architecture')
    installer = base / 'compilation/android/platform' / f'build-{architecture}' / 'build/venv'
    if not installer.exists():
        return False
    if installer.is_symlink() or not installer.resolve().is_relative_to(base.resolve()):
        raise RuntimeError('Refusing to remove an installer environment outside its managed build directory')
    shutil.rmtree(installer)
    return True


def prepare_official_config(stage, output, sdk, ndk, wheels):
    import PySide6
    template = Path(PySide6.__file__).parent / 'scripts/deploy_lib/default.spec'
    config = configparser.ConfigParser(interpolation=None)
    config.read(template, encoding='utf-8')
    fields = {
        'app': {'title': 'GiftFinder', 'project_dir': str(stage),
                'input_file': str(stage / 'main.py'), 'exec_directory': str(output),
                'icon': str(stage / 'giftfinder/icon.png')},
        'android': {'wheel_pyside': str(wheels[0]), 'wheel_shiboken': str(wheels[1])},
        'python': {'android_packages': 'buildozer==1.6.0,cython==0.29.37'},
        'buildozer': {'ndk_path': str(ndk), 'sdk_path': str(sdk), 'mode': 'debug'},
    }
    for section, values in fields.items():
        if not config.has_section(section):
            config.add_section(section)
        for key, value in values.items():
            config.set(section, key, value)
    target = stage / 'pysidedeploy.spec'
    with target.open('w', encoding='utf-8') as stream:
        config.write(stream)
    return target


def ensure_declared_qt_plugins(config_path, wheel, architecture):
    """Honor both ./plugins and plugins paths in the wheel dependency manifests.

    The Qt 6.12 deploy helper currently recognizes only the former spelling,
    although the 6.12 Network manifest uses the latter for TLS and networking.
    """
    config = configparser.ConfigParser(interpolation=None)
    config.read(config_path, encoding='utf-8')
    modules = [value.strip() for value in config.get('qt', 'modules').split(',') if value.strip()]
    previous = {value.strip() for value in config.get('android', 'plugins', fallback='').split(',') if value.strip()}
    selected = set(previous)
    suffix = '_' + architecture + '.so'
    with zipfile.ZipFile(wheel) as package:
        members = package.namelist()
        for module in modules:
            manifest_suffix = f'Qt6{module}_{architecture}-android-dependencies.xml'
            manifests = [name for name in members if name.endswith('/' + manifest_suffix)]
            for manifest in manifests:
                root = ET.fromstring(package.read(manifest))
                for element in root.iter('bundled'):
                    directory = element.get('file', '').removeprefix('./').rstrip('/')
                    if not directory.startswith('plugins/') or '..' in directory.split('/'):
                        continue
                    prefix = 'PySide6/Qt/' + directory + '/'
                    for name in members:
                        basename = name.rsplit('/', 1)[-1]
                        if name.startswith(prefix) and basename.startswith('libplugins_') and basename.endswith(suffix):
                            selected.add(basename[len('libplugins_'):-len(suffix)])
    if selected == previous:
        return False
    config.set('android', 'plugins', ','.join(sorted(selected)))
    with config_path.open('w', encoding='utf-8') as stream:
        config.write(stream)
    return True


def include_native_qt_plugins(apk, config_path, wheel, architecture):
    """Include declared plugins even when an older native recipe cache is reused.

    The input APK is unsigned. Alignment and signing happen only after this step.
    """
    config = configparser.ConfigParser(interpolation=None)
    config.read(config_path, encoding='utf-8')
    plugins = [value.strip() for value in config.get('android', 'plugins', fallback='').split(',') if value.strip()]
    added = []
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(apk, 'a') as destination:
        names = set(destination.namelist())
        for plugin in plugins:
            if not re.fullmatch(r'[A-Za-z0-9_]+', plugin):
                raise RuntimeError('Invalid Qt plugin name in generated configuration')
            category, _, _ = plugin.partition('_')
            filename = f'libplugins_{plugin}_{architecture}.so'
            member = f'lib/{architecture}/{filename}'
            if member in names:
                continue
            origin = f'PySide6/Qt/plugins/{category}/{filename}'
            info = zipfile.ZipInfo(member)
            info.external_attr = 0o100644 << 16
            # Uncompressed libraries are required when extractNativeLibs is false.
            destination.writestr(info, source.read(origin), compress_type=zipfile.ZIP_STORED)
            added.append(plugin)
    return added


def patch_buildozer(stage, output, app_version, architecture):
    target = stage / 'buildozer.spec'
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(target, encoding='utf-8')
    if not config.has_section('app') or config.get('app', 'p4a.bootstrap') != 'qt':
        raise RuntimeError('Official Qt bootstrap was not generated')
    legacy_storage = {'READ_EXTERNAL_STORAGE', 'WRITE_EXTERNAL_STORAGE'}
    permissions = {value.strip() for value in config.get('app', 'android.permissions', fallback='').split(',')
                   if value.strip() and value.strip().rsplit('.', 1)[-1] not in legacy_storage}
    if not any(value.rsplit('.', 1)[-1] == 'INTERNET' for value in permissions):
        permissions.add('INTERNET')
    major, minor, patch = map(int, app_version.split('.'))
    fields = {
        'package.name': 'giftfinder', 'package.domain': 'org.giftfinder',
        'version': app_version, 'android.numeric_version': str(major * 1000000 + minor * 10000 + patch * 100),
        'source.dir': str(stage), 'source.include_exts': 'py,png,jpg,jpeg,json,svg,txt,md,pem,qml,js',
        'source.include_patterns': 'third-party/*,third-party/**/*,UNLICENSE,THIRD_PARTY_NOTICES.txt',
        'source.exclude_dirs': '.git,.buildozer,deployment,__pycache__',
        # p4a records recipe names in lowercase and compares them case-sensitively
        # when choosing an existing native distribution.
        'requirements': 'python3,sqlite3,openssl,shiboken6,pyside6,' + ','.join(PURE_REQUIREMENTS),
        'android.archs': architecture, 'android.api': '35', 'android.minapi': '28', 'android.ndk_api': '28',
        'android.accept_sdk_license': 'True', 'android.permissions': ','.join(sorted(permissions)),
        'android.release_artifact': 'apk', 'android.debug_artifact': 'apk',
        'android.no-byte-compile-python': 'True', 'orientation': 'all', 'fullscreen': '0',
    }
    if architecture == 'x86_64':
        # A separate launcher only adds lifecycle logs to the labelled smoke APK.
        # Normal ARM releases keep the official, non-debuggable Qt launcher.
        java = stage.parent / 'smoke-java/org/giftfinder/diagnostics/GiftFinderDiagnosticsActivity.java'
        java.parent.mkdir(parents=True, exist_ok=True)
        java.write_text('''package org.giftfinder.diagnostics;
import android.os.Bundle;
import android.util.Log;
public class GiftFinderDiagnosticsActivity extends org.kivy.android.PythonActivity {
    @Override public void onCreate(Bundle state) {
        Log.i("GiftFinderLifecycle", "before PythonActivity.onCreate");
        super.onCreate(state);
        Log.i("GiftFinderLifecycle", "after PythonActivity.onCreate; finishing=" + isFinishing());
    }
    @Override public void finish() {
        Log.i("GiftFinderLifecycle", "Activity.finish requested", new Throwable("finish caller"));
        super.finish();
    }
    @Override public void onDestroy() {
        Log.i("GiftFinderLifecycle", "Activity.onDestroy; finishing=" + isFinishing()
              + "; changingConfigurations=" + isChangingConfigurations()
              + "; configurationChanges=" + getChangingConfigurations(),
              new Throwable("destroy caller"));
        super.onDestroy();
    }
}
''', encoding='utf-8')
        fields['android.add_src'] = str(stage.parent / 'smoke-java')
        fields['android.entrypoint'] = 'org.giftfinder.diagnostics.GiftFinderDiagnosticsActivity'
    for key, value in fields.items():
        config.set('app', key, value)
    config.set('buildozer', 'bin_dir', str(output))
    # Keep native compilation outside the directory purged by pyside6 --init.
    config.set('buildozer', 'build_dir', str(stage.parent / 'compilation'))
    with target.open('w', encoding='utf-8') as stream:
        config.write(stream)


def inspect_apk(apk, architecture):
    with zipfile.ZipFile(apk) as package:
        names = package.namelist()
        for name in names:
            if name.endswith(('private.tar', 'libpybundle.so')):
                try:
                    with tarfile.open(fileobj=io.BytesIO(package.read(name)), mode='r:*') as archive:
                        names += [item.name for item in archive.getmembers()]
                except tarfile.ReadError:
                    if name.endswith('private.tar'):
                        raise
        required = ('catalog_full.json', 'monochrome_pairs.json', 'rates_seed.json',
                    'themes_curated.json', 'requests/__init__.py', 'bs4/__init__.py',
                    'certifi/cacert.pem', '_sqlite3', '_ssl')
        missing = [suffix for suffix in required if not any(suffix in name for name in names)]
        if missing:
            raise RuntimeError(f'APK missing application resources or dependencies: {missing}')
        if not any(name.startswith(f'lib/{architecture}/') for name in names):
            raise RuntimeError(f'APK does not contain {architecture} native libraries')
        tls_plugin = f'lib/{architecture}/libplugins_tls_qopensslbackend_{architecture}.so'
        if tls_plugin not in names:
            raise RuntimeError('APK is missing its native Qt OpenSSL TLS backend')
    return {'resources_and_dependencies_present': True, 'native_architecture': architecture,
            'qt_openssl_tls_plugin_packaged': True}


def manifest_metadata(badging):
    def integer_field(pattern):
        match = re.search(pattern, badging, re.MULTILINE)
        return int(match.group(1)) if match else None
    return {
        'minimum_android_sdk': integer_field(r"^sdkVersion:'(\d+)'"),
        'target_android_sdk': integer_field(r"^targetSdkVersion:'(\d+)'"),
        'android_version_code': integer_field(r"^package:.*?versionCode='(\d+)'"),
        'android_permissions': sorted(set(re.findall(r"^uses-permission(?:-sdk-\d+)?: name='([^']+)'", badging, re.MULTILINE))),
    }


def input_method_visible(dump):
    shown = re.search(r'\bmInputShown\s*[=:]\s*(true|false)', dump, re.IGNORECASE)
    if shown:
        return shown.group(1).lower() == 'true'
    visibility = re.search(r'\bmImeWindowVis\s*=\s*(0x[0-9a-f]+)', dump, re.IGNORECASE)
    if visibility:
        return bool(int(visibility.group(1), 16) & 2)
    raise RuntimeError('Cannot determine the Android input-method visibility for the Back test')


def build(args):
    if sys.platform not in ('linux', 'darwin'):
        raise RuntimeError('Official PySide6 Android builds require a Linux or macOS host')
    if args.smoke and args.arch != 'x86_64':
        raise RuntimeError('Offline smoke mode is reserved for the x86_64 emulator package')
    sdk = Path(args.sdk or os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT', '')).resolve()
    ndk = Path(args.ndk).resolve() if args.ndk else sdk / 'ndk' / NDK_VERSION
    if not (sdk / 'build-tools/35.0.0/apksigner').is_file() or not ndk.is_dir():
        raise RuntimeError('Android SDK build-tools 35.0.0 and NDK 28c must be installed first')
    ensure_sdk_compatibility(sdk)
    base = ROOT / 'build/android' / args.arch
    base.mkdir(parents=True, exist_ok=True)
    stage = base / 'stage'
    stage.mkdir(exist_ok=True)
    binary = base / f'unsigned-{time.time_ns()}'
    binary.mkdir()
    tracked = stage_project(stage, smoke=args.smoke)
    cache = ROOT / 'build/android/wheels'
    cache.mkdir(parents=True, exist_ok=True)
    wheels = [download_wheel(component, ARCHITECTURES[args.arch], cache) for component in ('pyside6', 'shiboken6')]
    config = prepare_official_config(stage, binary, sdk, ndk, wheels)
    deploy = shutil.which('pyside6-android-deploy')
    if not deploy:
        raise RuntimeError('Install PySide6-Essentials 6.12.0 on this Linux/macOS host')
    environment = compilation_environment()
    initialize = [deploy, '--config-file', config, '--init', '--keep-deployment-files', '--no-install', '--force']
    run(initialize, cwd=stage, env=environment)
    if ensure_declared_qt_plugins(config, wheels[0], args.arch):
        # Regenerate only the tiny official recipes. Native compilation lives outside
        # the staging deployment directory, so its cache is preserved.
        run(initialize, cwd=stage, env=environment)
    app_version = version()
    patch_buildozer(stage, binary, app_version, args.arch)
    clear_cached_installer_environment(base, args.arch)
    run([sys.executable, '-m', 'buildozer', '-v', 'android', 'release'], cwd=stage, env=environment)
    apks = list(binary.glob('*.apk'))
    if len(apks) != 1:
        raise RuntimeError(f'Expected one built APK, found {len(apks)}')
    added_plugins = include_native_qt_plugins(apks[0], config, wheels[0], args.arch)
    checks = inspect_apk(apks[0], args.arch)
    destination = ROOT / 'release-dist'
    destination.mkdir(exist_ok=True)
    label = '-smoke' if args.smoke else ''
    target = destination / f'GiftFinder-{app_version}-Android-{args.arch}{label}.apk'
    keystore = os.environ.get('GIFT_FINDER_ANDROID_KEYSTORE')
    for name in ('ANDROID_KEYSTORE_PASSWORD', 'ANDROID_KEY_PASSWORD', 'ANDROID_KEY_ALIAS'):
        if not os.environ.get(name):
            raise RuntimeError(f'Missing signing environment variable: {name}')
    if not keystore or not Path(keystore).is_file():
        raise RuntimeError('Set GIFT_FINDER_ANDROID_KEYSTORE to the stable, private signing keystore')
    apksigner = sdk / 'build-tools/35.0.0/apksigner'
    zipalign = sdk / 'build-tools/35.0.0/zipalign'
    aligned = binary / 'aligned.apk'
    run([zipalign, '-P', '16', '-f', '4', apks[0], aligned])
    run([apksigner, 'sign', '--ks', keystore, '--ks-key-alias', os.environ['ANDROID_KEY_ALIAS'],
         '--ks-pass', 'env:ANDROID_KEYSTORE_PASSWORD', '--key-pass', 'env:ANDROID_KEY_PASSWORD',
         '--out', target, aligned])
    run([zipalign, '-c', '-P', '16', '4', target])
    signature = run([apksigner, 'verify', '--verbose', '--print-certs', target], capture=True)
    certificate = re.search(r'Signer #1 certificate SHA-256 digest: ([a-fA-F0-9:]+)', signature)
    if not certificate:
        raise RuntimeError('Unable to verify signing certificate')
    badging = run([sdk / 'build-tools/35.0.0/aapt', 'dump', 'badging', target], capture=True)
    if f"name='{PACKAGE_ID}'" not in badging:
        raise RuntimeError('The APK application ID does not match GiftFinder')
    metadata = manifest_metadata(badging)
    if any(permission.rsplit('.', 1)[-1] in {'READ_EXTERNAL_STORAGE', 'WRITE_EXTERNAL_STORAGE'}
           for permission in metadata['android_permissions']):
        raise RuntimeError('APK still declares unnecessary legacy external storage access')
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (destination / f'SHA256-Android-{args.arch}.txt').write_text(f'{digest}  {target.name}\n', encoding='ascii')
    evidence = {'version': app_version, 'package_id': PACKAGE_ID, 'architecture': args.arch,
                'offline_smoke_package': args.smoke, 'qt_version': QT_VERSION,
                'tracked_application_files': len(tracked), 'apk': target.name, 'sha256': digest,
                'signature_verified': True, 'zip_alignment_16kb_verified': True,
                'certificate_sha256': certificate.group(1),
                'qt_native_plugins_added_after_cached_recipe': added_plugins,
                **metadata, **checks}
    (base / 'verification.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, indent=2), flush=True)


def emulator_test(args):
    """Exercise the installed APK on an already booted, headless Android emulator."""
    apk = Path(args.apk).resolve()
    output = Path(args.evidence).resolve()
    output.mkdir(parents=True, exist_ok=True)
    adb = shutil.which('adb')
    if not adb:
        raise RuntimeError('adb must be available')
    # Incremental install can report success while APK blocks are still streaming.
    # Test the normal, fully installed release package before launching Qt.
    run([adb, 'install', '--no-incremental', '-r', apk], timeout=120)
    run([adb, 'logcat', '-c'])
    run([adb, 'shell', 'am', 'force-stop', PACKAGE_ID])
    resolved = run([adb, 'shell', 'cmd', 'package', 'resolve-activity', '--brief', PACKAGE_ID], capture=True)
    activities = [line.strip() for line in resolved.splitlines() if line.strip().startswith(PACKAGE_ID + '/')]
    if len(activities) != 1:
        raise RuntimeError('Unable to resolve the installed Android launcher activity')
    run([adb, 'shell', 'am', 'start', '-W', '-n', activities[0]], timeout=120)
    deadline = time.monotonic() + 90
    logs = ''
    required_markers = ('GIFTFINDER_ANDROID_READY', 'GIFTFINDER_ANDROID_TLS_READY',
                        'GIFTFINDER_ANDROID_IMAGE_READY')
    while time.monotonic() < deadline:
        process = subprocess.run([adb, 'shell', 'pidof', PACKAGE_ID], text=True, capture_output=True)
        current_pid = process.stdout.strip().split()
        log_command = [adb, 'logcat', '-d', '-v', 'threadtime']
        if len(current_pid) == 1 and current_pid[0].isdigit():
            log_command += ['--pid', current_pid[0]]
        result = subprocess.run(log_command, text=True, capture_output=True, check=True)
        logs = result.stdout
        if all(marker in logs for marker in required_markers):
            break
        if current_pid and any(marker in logs for marker in ('FATAL EXCEPTION', 'Fatal Python error:', 'Traceback (most recent call last):')):
            break
        time.sleep(2)
    (output / 'startup-logcat.txt').write_text(logs, encoding='utf-8')
    missing_markers = [marker for marker in required_markers if marker not in logs]
    if missing_markers:
        with (output / 'android-startup-failure.png').open('wb') as stream:
            subprocess.run([adb, 'exec-out', 'screencap', '-p'], stdout=stream, timeout=20)
        diagnostics = subprocess.run([adb, 'shell', 'dumpsys', 'activity', 'activities'],
                                     text=True, capture_output=True, timeout=20)
        (output / 'startup-activities.txt').write_text(diagnostics.stdout, encoding='utf-8')
        raise RuntimeError(f'Android startup/network checks did not complete: {missing_markers}; inspect logcat')
    time.sleep(5)
    pid = run([adb, 'shell', 'pidof', PACKAGE_ID], capture=True).strip()
    if not pid:
        raise RuntimeError('The Android application exited after startup')
    final_logs = run([adb, 'logcat', '-d', '--pid', pid, '-v', 'threadtime'], capture=True)
    (output / 'application-logcat.txt').write_text(final_logs, encoding='utf-8')
    if any(marker in final_logs for marker in ('FATAL EXCEPTION', 'Fatal Python error:', 'Traceback (most recent call last):')):
        raise RuntimeError('Python or Android crash detected after startup')
    screenshot = output / 'android-home.png'
    with screenshot.open('wb') as stream:
        subprocess.run([adb, 'exec-out', 'screencap', '-p'], check=True, stdout=stream)
    from PySide6.QtGui import QImage
    image = QImage(str(screenshot))
    if image.isNull() or image.width() < 320 or image.height() < 480:
        raise RuntimeError('Invalid Android screenshot')
    colors = {image.pixelColor(x, y).rgba() for x in range(0, image.width(), 17) for y in range(0, image.height(), 19)}
    if len(colors) < 16:
        raise RuntimeError('Android screenshot is blank or nearly blank')
    run([adb, 'shell', 'uiautomator', 'dump', '/sdcard/giftfinder-ui.xml'], timeout=45)
    hierarchy = run([adb, 'exec-out', 'cat', '/sdcard/giftfinder-ui.xml'], capture=True)
    (output / 'home-accessibility.xml').write_text(hierarchy, encoding='utf-8')
    tree = ET.fromstring(hierarchy)
    filters = next((node for node in tree.iter('node') if
                    node.get('text') == 'Filters' or node.get('content-desc') == 'Filters'), None)
    if filters is None:
        raise RuntimeError('The mobile Filters button is missing from Android accessibility')
    bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', filters.get('bounds', ''))
    if not bounds:
        raise RuntimeError('The Android Filters button has invalid screen bounds')
    left, top, right, bottom = map(int, bounds.groups())
    run([adb, 'shell', 'input', 'tap', str((left + right) // 2), str((top + bottom) // 2)])
    time.sleep(3)
    tapped_logs = run([adb, 'logcat', '-d', '--pid', pid, '-v', 'threadtime'], capture=True)
    (output / 'application-logcat.txt').write_text(tapped_logs, encoding='utf-8')
    if 'GIFTFINDER_ANDROID_FILTERS_OPEN' not in tapped_logs:
        raise RuntimeError('Tapping the Android Filters button did not open its sheet')
    if any(marker in tapped_logs for marker in ('FATAL EXCEPTION', 'Fatal Python error:', 'Traceback (most recent call last):')):
        raise RuntimeError('Crash detected while opening the mobile filter sheet')
    with (output / 'android-filters.png').open('wb') as stream:
        subprocess.run([adb, 'exec-out', 'screencap', '-p'], check=True, stdout=stream)
    ime_before = run([adb, 'shell', 'dumpsys', 'input_method'], capture=True, timeout=30)
    (output / 'input-method-before-back.txt').write_text(ime_before, encoding='utf-8')
    ime_was_visible = input_method_visible(ime_before)
    back_presses = 0
    if ime_was_visible:
        # The first system Back may legitimately dismiss the soft keyboard.
        run([adb, 'shell', 'input', 'keyevent', 'KEYCODE_BACK'], timeout=15)
        back_presses += 1
        time.sleep(1)
        ime_after = run([adb, 'shell', 'dumpsys', 'input_method'], capture=True, timeout=30)
        (output / 'input-method-after-ime-back.txt').write_text(ime_after, encoding='utf-8')
        if input_method_visible(ime_after):
            raise RuntimeError('A system Back did not dismiss the visible Android keyboard')
    back_logs = run([adb, 'logcat', '-d', '--pid', pid, '-v', 'threadtime'], capture=True)
    if 'GIFTFINDER_ANDROID_FILTERS_CLOSED' not in back_logs:
        run([adb, 'shell', 'input', 'keyevent', 'KEYCODE_BACK'], timeout=15)
        back_presses += 1
        time.sleep(1)
        back_logs = run([adb, 'logcat', '-d', '--pid', pid, '-v', 'threadtime'], capture=True)
    (output / 'application-logcat.txt').write_text(back_logs, encoding='utf-8')
    if any(marker in back_logs for marker in ('FATAL EXCEPTION', 'Fatal Python error:', 'Traceback (most recent call last):')):
        raise RuntimeError('Crash detected while returning from the mobile filter sheet')
    if 'GIFTFINDER_ANDROID_FILTERS_CLOSED' not in back_logs:
        raise RuntimeError('One system Back with the keyboard closed did not close the filter sheet')
    if not run([adb, 'shell', 'pidof', PACKAGE_ID], capture=True).strip():
        raise RuntimeError('System Back exited the application instead of only closing Filters')
    with (output / 'android-after-back.png').open('wb') as stream:
        subprocess.run([adb, 'exec-out', 'screencap', '-p'], check=True, stdout=stream)
    evidence = {'apk': apk.name, 'package_id': PACKAGE_ID, 'emulator_architecture': 'x86_64',
                'ready_marker_seen': True, 'process_alive_after_startup': True,
                'python_ssl_and_sqlite_runtime_checks': True, 'qt_ssl_backend_runtime_check': True,
                'uncached_public_image_loaded_over_https': True,
                'accessible_filters_button_tapped': True, 'mobile_filters_sheet_opened': True,
                'filters_closed_by_system_back': True, 'process_alive_after_filter_back': True,
                'soft_keyboard_was_visible': ime_was_visible, 'system_back_presses_including_keyboard_dismissal': back_presses,
                'no_python_crash_in_application_log': True, 'screenshot_size': [image.width(), image.height()],
                'sampled_colors': len(colors), 'offline_smoke_package': True,
                'physical_arm64_device_tested': False, 'live_marketplace_search_tested': False}
    (output / 'emulator-verification.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    package = commands.add_parser('build')
    package.add_argument('--arch', choices=ARCHITECTURES, required=True)
    package.add_argument('--sdk')
    package.add_argument('--ndk')
    package.add_argument('--smoke', action='store_true')
    emulator = commands.add_parser('emulator-test')
    emulator.add_argument('--apk', required=True)
    emulator.add_argument('--evidence', default='build/android/x86_64/emulator')
    args = parser.parse_args()
    if args.command == 'build':
        build(args)
    else:
        emulator_test(args)


if __name__ == '__main__':
    main()
