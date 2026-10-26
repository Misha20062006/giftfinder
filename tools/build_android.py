"""Build a signed Android APK with the official Qt for Python Android recipes.

Run on Linux x86_64 with JDK 17, Android SDK 35 and NDK 28c. Credentials are read
only from the environment; generated projects, wheels and profiles stay in build/.
"""
from __future__ import annotations

import argparse
import atexit
import ast
import configparser
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.android_elf import audit_apk
from tools.android_qt_platform import prepare_platform, verify_packaged_platform


ROOT = Path(__file__).resolve().parents[1]
INPUTS = json.loads((ROOT / 'mobile/android-build-inputs.json').read_text(encoding='utf-8'))
QT_VERSION = INPUTS['qt_version']
PACKAGE_ID = 'org.giftfinder.giftfinder'
NDK_VERSION = INPUTS['ndk_version']
ARCHITECTURES = {'arm64-v8a': 'aarch64', 'x86_64': 'x86_64'}
PURE_REQUIREMENTS = tuple(item['requirement'] for item in INPUTS['pure_wheels'])


def compilation_environment():
    """Build tools sometimes print their environment; never give them signing secrets."""
    environment = os.environ.copy()
    for key in ('ANDROID_KEYSTORE_BASE64', 'ANDROID_KEYSTORE_PASSWORD',
                'ANDROID_KEY_PASSWORD', 'ANDROID_KEY_ALIAS', 'GIFT_FINDER_ANDROID_KEYSTORE'):
        environment.pop(key, None)
    environment['CHARSET_NORMALIZER_USE_CYTHON'] = '0'
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


def download_verified(url, expected, target):
    if not re.fullmatch('[0-9a-f]{64}', expected) or not url.startswith('https://'):
        raise RuntimeError('Invalid pinned build input URL or SHA-256')
    target = Path(target)
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.part')
    print('Downloading pinned build input:', target.name, flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as output:
        shutil.copyfileobj(response, output)
    if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f'Pinned checksum mismatch: {target.name}')
    temporary.replace(target)
    return target


def download_wheel(component, architecture, cache):
    entry = INPUTS['qt_wheels'][architecture][component]
    return download_verified(entry['url'], entry['sha256'], cache / entry['filename'])


def build_fingerprint(inputs=None, templates=None):
    if templates is None:
        import PySide6
        library = Path(PySide6.__file__).parent / 'scripts/deploy_lib'
        templates = {str(path.relative_to(library)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in library.rglob('*') if path.is_file() and path.suffix in {'.py', '.jinja', '.spec'}}
    payload = {'inputs': inputs if inputs is not None else INPUTS, 'qt_recipe_templates': templates,
               'build_hooks': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                               for name in ('mobile/android_hook.py', 'mobile/android_runtime.py',
                                            'tools/android_qt_platform.py', 'mobile/qt_platform/CMakeLists.txt')}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()


def smoke_probe_metadata():
    values = {}
    tree = ast.parse((ROOT / 'mobile/main.py').read_text(encoding='utf-8-sig'))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {'ANDROID_SMOKE_IMAGE_URL', 'ANDROID_SMOKE_IMAGE_SHA256'}:
                    values[target.id] = ast.literal_eval(node.value)
    if set(values) != {'ANDROID_SMOKE_IMAGE_URL', 'ANDROID_SMOKE_IMAGE_SHA256'}:
        raise RuntimeError('The native HTTPS smoke probe must declare its exact immutable URL and content SHA-256')
    return {'url': values['ANDROID_SMOKE_IMAGE_URL'], 'sha256': values['ANDROID_SMOKE_IMAGE_SHA256'],
            'host': urllib.parse.urlparse(values['ANDROID_SMOKE_IMAGE_URL']).hostname,
            'purpose': 'uncached public HTTPS transport and image decoding; provider integration is separate'}


def prepare_runtime_inputs(fingerprint, environment):
    import importlib.metadata
    import shiboken6_generator
    from mobile.android_runtime import verified_wheel
    if importlib.metadata.version('shiboken6-generator') != QT_VERSION:
        raise RuntimeError('The exact pinned Qt Shiboken host generator is required')
    base = ROOT / 'build/android/runtime-inputs' / fingerprint
    base.mkdir(parents=True, exist_ok=True)
    (base / 'inputs.json').write_text(json.dumps(INPUTS, indent=2) + '\n', encoding='utf-8')
    for dependency in INPUTS['pure_wheels']:
        wheel = download_verified(dependency['url'], dependency['sha256'], base / 'pure-wheels' / dependency['filename'])
        verified_wheel(wheel, dependency['sha256'])
    commit = INPUTS['shiboken_source']['commit']
    for relative, digest in INPUTS['shiboken_source']['files'].items():
        url = f'https://raw.githubusercontent.com/qtproject/pyside-pyside-setup/{commit}/{relative}'
        download_verified(url, digest, base / 'source' / relative)
    source = base / 'source/sources/shiboken6/shibokenmodule'
    generated = base / 'generated'
    generator = Path(shiboken6_generator.__file__).parent / ('shiboken6.exe' if os.name == 'nt' else 'shiboken6')
    run([generator, '--generator-set=shiboken', '--avoid-protected-hack',
         '--output-directory=' + str(generated), source / 'nothing.h', source / 'typesystem_shiboken.xml'], env=environment)
    if not (generated / 'Shiboken/shiboken_module_wrapper.cpp').is_file():
        raise RuntimeError('Official Shiboken generator did not create the target wrapper source')
    return base


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


def clear_cached_installer_environment(base, architecture, *, compilation=None):
    """Regenerate p4a's disposable pip venv, preserving every compiled recipe."""
    if architecture not in ARCHITECTURES:
        raise RuntimeError('Unknown Android architecture')
    compilation = compilation or base / 'compilation'
    installer = compilation / 'android/platform' / f'build-{architecture}' / 'build/venv'
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


def patch_buildozer(stage, output, app_version, architecture, *, compilation=None):
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
        # Universal application wheels are installed by our before_apk_build hook.
        # Do not let host pip choose Linux accelerators for the Android target.
        'requirements': 'python3==' + INPUTS['target_python'] + ',sqlite3,openssl,shiboken6,pyside6',
        'p4a.commit': INPUTS['p4a_commit'],
        'android.archs': architecture, 'android.api': '35', 'android.minapi': '28', 'android.ndk_api': '28',
        'android.accept_sdk_license': 'True', 'android.permissions': ','.join(sorted(permissions)),
        'android.release_artifact': 'apk', 'android.debug_artifact': 'apk',
        'android.no-byte-compile-python': 'True', 'orientation': 'all', 'fullscreen': '0',
        'p4a.hook': str(ROOT / 'mobile/android_hook.py'),
    }
    if architecture == 'x86_64':
        # A separate launcher only adds lifecycle logs to the labelled smoke APK.
        # Normal ARM releases keep the official, non-debuggable Qt launcher.
        java = stage.parent / 'smoke-java/org/giftfinder/diagnostics/GiftFinderDiagnosticsActivity.java'
        java.parent.mkdir(parents=True, exist_ok=True)
        java.write_text('''package org.giftfinder.diagnostics;
import android.os.Bundle;
import android.os.Build;
import android.util.Log;
import android.view.KeyEvent;
import android.view.WindowInsets;
public class GiftFinderDiagnosticsActivity extends org.kivy.android.PythonActivity {
    private String imeInsets() {
        WindowInsets insets = getWindow().getDecorView().getRootWindowInsets();
        if (insets == null || Build.VERSION.SDK_INT < 30) return "unknown";
        return Boolean.toString(insets.isVisible(WindowInsets.Type.ime()));
    }
    @Override public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK)
            Log.i("GiftFinderInput", "physicalBack=down repeat=" + event.getRepeatCount()
                  + "; imeInsetsVisible=" + imeInsets());
        boolean handled = super.onKeyDown(keyCode, event);
        if (keyCode == KeyEvent.KEYCODE_BACK)
            Log.i("GiftFinderInput", "physicalBack=down handled=" + handled);
        return handled;
    }
    @Override public boolean onKeyUp(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK)
            Log.i("GiftFinderInput", "physicalBack=up repeat=" + event.getRepeatCount()
                  + "; imeInsetsVisible=" + imeInsets());
        return super.onKeyUp(keyCode, event);
    }
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
    config.set('buildozer', 'build_dir', str(compilation or stage.parent / 'compilation'))
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
        binding_names = [f'lib/{architecture}/libQt{module}.abi3.so'
                         for module in ('Core', 'Gui', 'Widgets', 'Network', 'Svg')]
        if any(name not in names for name in binding_names):
            raise RuntimeError('APK is missing installable lib-prefixed Qt binding preload libraries')
        if any(re.fullmatch(rf'lib/{re.escape(architecture)}/Qt\w+\.abi3\.so', name) for name in names):
            raise RuntimeError('APK contains Qt binding preload libraries that Android will not extract')
    native = audit_apk(apk, architecture)
    return {'resources_and_dependencies_present': True, 'native_architecture': architecture,
            'qt_openssl_tls_plugin_packaged': True,
            'qt_binding_preloads_use_installable_library_names': True, **native}


def manifest_metadata(badging):
    def integer_field(pattern):
        match = re.search(pattern, badging, re.MULTILINE)
        return int(match.group(1)) if match else None
    return {
        'minimum_android_sdk': integer_field(r"^sdkVersion:'(\d+)'"),
        'target_android_sdk': integer_field(r"^targetSdkVersion:'(\d+)'"),
        'android_version_code': integer_field(r"^package:.*?versionCode='(\d+)'"),
        'android_permissions': sorted(set(re.findall(r"^uses-permission(?:-sdk-\d+)?: name='([^']+)'", badging, re.MULTILINE))),
        'application_debuggable': bool(re.search(r'^application-debuggable\b', badging, re.MULTILINE)),
        'launcher_activity': next(iter(re.findall(r"^launchable-activity: name='([^']+)'", badging, re.MULTILINE)), None),
    }


def input_method_visible(dump):
    visibility = re.search(r'\bmImeWindowVis\s*=\s*(0x[0-9a-f]+)', dump, re.IGNORECASE)
    if visibility:
        return bool(int(visibility.group(1), 16) & 2)
    shown = re.search(r'\bmInputShown\s*[=:]\s*(true|false)', dump, re.IGNORECASE)
    if shown:
        return shown.group(1).lower() == 'true'
    raise RuntimeError('Cannot determine the Android input-method visibility for the Back test')


def native_hierarchy(adb, output, name):
    run([adb, 'shell', 'uiautomator', 'dump', '/sdcard/giftfinder-regression.xml'], timeout=45)
    source = run([adb, 'exec-out', 'cat', '/sdcard/giftfinder-regression.xml'], capture=True)
    (output / (name + '.xml')).write_text(source, encoding='utf-8')
    return ET.fromstring(source)


def native_bounds(node):
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', '') if node is not None else '')
    if not match:
        return None
    x1, y1, x2, y2 = map(int, match.groups())
    return (x1, y1, x2, y2) if x1 < x2 and y1 < y2 else None


def native_find(tree, predicate, purpose):
    nodes = [node for node in tree.iter('node') if predicate(node) and native_bounds(node)
             and node.get('enabled') == 'true']
    if len(nodes) != 1:
        raise RuntimeError(f'Cannot find one visible Android {purpose}')
    return nodes[0]


def native_label(node, label):
    return node.get('text') == label or node.get('content-desc') == label


def native_id(node, name):
    value = node.get('resource-id', '')
    return value == name or value.endswith('.' + name) or value.endswith(':id/' + name)


def native_tap(adb, node):
    x1, y1, x2, y2 = native_bounds(node)
    run([adb, 'shell', 'input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2)], timeout=15)


def main_popup_and_language_test(adb, output, pid):
    tree = native_hierarchy(adb, output, 'popup-home')
    native_tap(adb, native_find(tree, lambda n: native_label(n, 'Actions'), 'Actions button'))
    tree = native_hierarchy(adb, output, 'popup-actions-open')
    native_find(tree, lambda n: native_label(n, 'Rates'), 'Rates menu entry')
    run([adb, 'shell', 'input', 'keyevent', 'KEYCODE_BACK'], timeout=15)
    tree = native_hierarchy(adb, output, 'popup-actions-after-back')
    native_find(tree, lambda n: native_label(n, 'Filters'), 'main Filters button after popup Back')
    if any(native_label(n, 'Rates') and native_bounds(n) for n in tree.iter('node')):
        raise RuntimeError('One Back did not close the Actions menu')
    if run([adb, 'shell', 'pidof', PACKAGE_ID], capture=True).strip() != pid:
        raise RuntimeError('Back from Actions exited the application')
    native_tap(adb, native_find(tree, lambda n: native_id(n, 'mobileLanguageButton'), 'language button'))
    swipes = 0
    for attempt in range(8):
        tree = native_hierarchy(adb, output, 'language-scroll-' + str(attempt))
        listing = native_find(tree, lambda n: native_id(n, 'mobileLanguageList'), 'language list after touch swipe')
        japanese = next((n for n in tree.iter('node') if native_label(n, '日本語') and native_bounds(n)), None)
        if japanese is not None and swipes:
            break
        x1, y1, x2, y2 = native_bounds(listing)
        run([adb, 'shell', 'input', 'swipe', str((x1 + x2) // 2), str(y1 + (y2 - y1) * 4 // 5),
             str((x1 + x2) // 2), str(y1 + (y2 - y1) // 5), '350'], timeout=15)
        swipes += 1
        time.sleep(1)  # Let the injected kinetic gesture settle before an ordinary tap.
    else:
        raise RuntimeError('Finger swipes did not reach the lower Japanese language row')
    with (output / 'android-language-scrolled.png').open('wb') as stream:
        subprocess.run([adb, 'exec-out', 'screencap', '-p'], check=True, stdout=stream, timeout=20)
    native_tap(adb, japanese)
    tree = native_hierarchy(adb, output, 'language-japanese-selected')
    button = native_find(tree, lambda n: native_id(n, 'mobileLanguageButton'), 'selected Japanese language button')
    if not re.search(r'\bJA\b', button.get('text', '') + ' ' + button.get('content-desc', '')):
        raise RuntimeError('An ordinary tap after language scrolling did not select Japanese')
    native_tap(adb, button)
    tree = native_hierarchy(adb, output, 'language-restore-english')
    native_tap(adb, native_find(tree, lambda n: native_label(n, 'English'), 'English language row'))
    tree = native_hierarchy(adb, output, 'language-english-selected')
    button = native_find(tree, lambda n: native_id(n, 'mobileLanguageButton'), 'restored English language button')
    if not re.search(r'\bEN\b', button.get('text', '') + ' ' + button.get('content-desc', '')):
        raise RuntimeError('English was not restored through the native language list')
    return swipes


def category_popup_draft_test(adb, output, pid):
    draft = 'egg'
    tree = native_hierarchy(adb, output, 'category-draft-start')
    search = native_find(tree, lambda n: native_id(n, 'mobileFilterListSearch'), 'filter draft search')
    native_tap(adb, search)
    tree = native_hierarchy(adb, output, 'category-draft-focused')
    search = native_find(tree, lambda n: native_id(n, 'mobileFilterListSearch'), 'focused filter draft search')
    if search.get('focused') != 'true':
        raise RuntimeError('The native filter search did not acquire input focus before typing')
    ready_ime = run([adb, 'shell', 'dumpsys', 'input_method'], capture=True, timeout=30)
    (output / 'category-ime-before-typing.txt').write_text(ready_ime, encoding='utf-8')
    if not re.search(r'\bpackageName\s*=\s*' + re.escape(PACKAGE_ID) + r'\b', ready_ime):
        raise RuntimeError('Android has not bound an input editor for the focused application')
    run([adb, 'shell', 'input', 'text', draft], timeout=15)
    tree = native_hierarchy(adb, output, 'category-draft-typed')
    ime = run([adb, 'shell', 'dumpsys', 'input_method'], capture=True, timeout=30)
    (output / 'category-ime-before-dismiss.txt').write_text(ime, encoding='utf-8')
    windows = run([adb, 'shell', 'dumpsys', 'window', 'windows'], capture=True, timeout=30)
    (output / 'category-windows-before-dismiss.txt').write_text(windows, encoding='utf-8')
    with (output / 'android-category-draft-before-back.png').open('wb') as stream:
        subprocess.run([adb, 'exec-out', 'screencap', '-p'], check=True, stdout=stream, timeout=20)
    search = native_find(tree, lambda n: native_id(n, 'mobileFilterListSearch'), 'entered filter draft')
    if draft not in (search.get('text', ''), search.get('content-desc', '')):
        raise RuntimeError('Android text injection did not enter the complete filter draft')
    if input_method_visible(ime):
        run([adb, 'shell', 'input', 'keyevent', 'KEYCODE_BACK'], timeout=15)
        time.sleep(1)
        ime = run([adb, 'shell', 'dumpsys', 'input_method'], capture=True, timeout=30)
        (output / 'category-ime-after-dismiss.txt').write_text(ime, encoding='utf-8')
        windows = run([adb, 'shell', 'dumpsys', 'window', 'windows'], capture=True, timeout=30)
        (output / 'category-windows-after-dismiss.txt').write_text(windows, encoding='utf-8')
    tree = native_hierarchy(adb, output, 'category-draft-before-popup')
    native_tap(adb, native_find(tree, lambda n: native_id(n, 'mobileFilterCategory'), 'filter category selector'))
    tree = native_hierarchy(adb, output, 'category-popup-open')
    native_find(tree, lambda n: native_label(n, 'Backdrop'), 'category popup Backdrop option')
    run([adb, 'shell', 'input', 'keyevent', 'KEYCODE_BACK'], timeout=15)
    tree = native_hierarchy(adb, output, 'category-popup-after-back')
    native_find(tree, lambda n: native_id(n, 'mobileFilterCategory'), 'category selector after popup Back')
    search = native_find(tree, lambda n: native_id(n, 'mobileFilterListSearch'), 'preserved filter draft')
    if draft not in (search.get('text', ''), search.get('content-desc', '')):
        raise RuntimeError('Back from the category popup did not preserve the draft text')
    logs = run([adb, 'logcat', '-d', '--pid', pid, '-v', 'threadtime'], capture=True)
    if 'GIFTFINDER_ANDROID_FILTERS_CLOSED' in logs:
        raise RuntimeError('Back from category popup closed the entire filter sheet')
    if run([adb, 'shell', 'pidof', PACKAGE_ID], capture=True).strip() != pid:
        raise RuntimeError('Back from category popup exited the application')


def csv_picker_test(adb, output, pid):
    """Save the explicitly synthetic smoke offer through Android's real SAF UI."""
    def hierarchy(name):
        run([adb, 'shell', 'uiautomator', 'dump', '/sdcard/giftfinder-csv.xml'], timeout=45)
        source = run([adb, 'exec-out', 'cat', '/sdcard/giftfinder-csv.xml'], capture=True)
        (output / (name + '.xml')).write_text(source, encoding='utf-8')
        return ET.fromstring(source)

    def tap(tree, predicate, purpose):
        nodes = [node for node in tree.iter('node') if predicate(node) and node.get('enabled') == 'true']
        if len(nodes) != 1:
            raise RuntimeError(f'Cannot locate the unique Android {purpose} control')
        bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', nodes[0].get('bounds', ''))
        if not bounds:
            raise RuntimeError(f'Invalid bounds for Android {purpose}')
        x1, y1, x2, y2 = map(int, bounds.groups())
        run([adb, 'shell', 'input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2)], timeout=15)

    tap(hierarchy('csv-home-accessibility'),
        lambda node: node.get('text') == 'Actions' or node.get('content-desc') == 'Actions', 'Actions menu')
    time.sleep(1)
    tap(hierarchy('csv-menu-accessibility'),
        lambda node: node.get('text') == 'Export CSV' or node.get('content-desc') == 'Export CSV', 'CSV export action')
    time.sleep(2)
    picker = hierarchy('csv-native-picker')
    if not any('documentsui' in node.get('package', '').lower() for node in picker.iter('node')):
        raise RuntimeError('CSV export did not open the native Android document picker')
    with (output / 'android-csv-picker.png').open('wb') as stream:
        subprocess.run([adb, 'exec-out', 'screencap', '-p'], check=True, stdout=stream, timeout=20)
    tap(picker, lambda node: any(node.get(key, '').strip().casefold() == 'save'
                                for key in ('text', 'content-desc')) and
        (node.get('clickable') == 'true' or node.get('class', '').endswith('Button')), 'document Save button')
    deadline = time.monotonic() + 30
    logs = ''
    while time.monotonic() < deadline:
        logs = run([adb, 'logcat', '-d', '--pid', pid, '-v', 'threadtime'], capture=True)
        if 'GIFTFINDER_ANDROID_CSV_SAVED' in logs:
            break
        if any(marker in logs for marker in ('FATAL EXCEPTION', 'Fatal Python error:', 'Traceback (most recent call last):')):
            break
        time.sleep(1)
    (output / 'application-logcat.txt').write_text(logs, encoding='utf-8')
    if 'GIFTFINDER_ANDROID_CSV_SAVED' not in logs:
        raise RuntimeError('Native Android CSV save and content URI readback did not complete')
    if any(marker in logs for marker in ('FATAL EXCEPTION', 'Fatal Python error:', 'Traceback (most recent call last):')):
        raise RuntimeError('Crash detected during native Android CSV export')
    if run([adb, 'shell', 'pidof', PACKAGE_ID], capture=True).strip() != pid:
        raise RuntimeError('The Android application did not survive native CSV document creation')
    with (output / 'android-csv-saved.png').open('wb') as stream:
        subprocess.run([adb, 'exec-out', 'screencap', '-p'], check=True, stdout=stream, timeout=20)


def build(args):
    if sys.platform != 'linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        raise RuntimeError('The pinned Qt Android backport currently requires a Linux x86_64 build host')
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
    fingerprint = build_fingerprint()
    compilation = base / 'compilation' / fingerprint
    runtime_inputs = prepare_runtime_inputs(fingerprint, environment)
    platform_rebuild = prepare_platform(runtime_inputs, INPUTS, args.arch, ndk, sdk, wheels[0],
                                        download_verified, environment, ROOT)
    environment['GIFT_FINDER_ANDROID_RUNTIME_INPUTS'] = str(runtime_inputs)
    initialize = [deploy, '--config-file', config, '--init', '--keep-deployment-files', '--no-install', '--force']
    run(initialize, cwd=stage, env=environment)
    if ensure_declared_qt_plugins(config, wheels[0], args.arch):
        # Regenerate only the tiny official recipes. Native compilation lives outside
        # the staging deployment directory, so its cache is preserved.
        run(initialize, cwd=stage, env=environment)
    app_version = version()
    patch_buildozer(stage, binary, app_version, args.arch, compilation=compilation)
    clear_cached_installer_environment(base, args.arch, compilation=compilation)
    run([sys.executable, '-m', 'buildozer', '-v', 'android', 'release'], cwd=stage, env=environment)
    apks = list(binary.glob('*.apk'))
    if len(apks) != 1:
        raise RuntimeError(f'Expected one built APK, found {len(apks)}')
    added_plugins = include_native_qt_plugins(apks[0], config, wheels[0], args.arch)
    checks = inspect_apk(apks[0], args.arch)
    platform_checks = verify_packaged_platform(apks[0], args.arch, platform_rebuild)
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
    if metadata['application_debuggable']:
        raise RuntimeError('Release APK must not be debuggable, including the offline smoke package')
    expected_activity = ('org.giftfinder.diagnostics.GiftFinderDiagnosticsActivity' if args.smoke
                         else 'org.kivy.android.PythonActivity')
    if metadata['launcher_activity'] != expected_activity:
        raise RuntimeError('The signed Android package has an unexpected launcher activity')
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
                'dependency_recipe_fingerprint': fingerprint,
                'ci_https_image_probe': smoke_probe_metadata(),
                'shiboken_rebuild': json.loads((runtime_inputs / ('rebuild-' + args.arch + '.json')).read_text(encoding='utf-8')),
                'qt_android_platform_rebuild': platform_checks,
                **metadata, **checks}
    (base / 'verification.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, indent=2), flush=True)


def start_android_log(adb, target, selector):
    """Keep app logs that would otherwise be lost if ADB disconnects mid-startup."""
    stream = Path(target).open('w', encoding='utf-8')
    process = subprocess.Popen([adb, 'logcat', *selector, '-v', 'threadtime'],
                               stdout=stream, stderr=subprocess.STDOUT, text=True)
    def close():
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        finally:
            stream.close()
    atexit.register(close)


def emulator_test(args):
    """Exercise the installed APK on an already booted, headless Android emulator."""
    apk = Path(args.apk).resolve()
    output = Path(args.evidence).resolve()
    output.mkdir(parents=True, exist_ok=True)
    adb = shutil.which('adb')
    if not adb:
        raise RuntimeError('adb must be available')
    page_size = int(run([adb, 'shell', 'getconf', 'PAGESIZE'], capture=True).strip())
    environment = {'actual_android_page_size': page_size, 'required_android_page_size': 16384,
                   'actual_device_abi': run([adb, 'shell', 'getprop', 'ro.product.cpu.abi'], capture=True).strip()}
    for name, property_name in (('actual_android_sdk', 'ro.build.version.sdk'),
                                ('actual_android_release', 'ro.build.version.release'),
                                ('actual_android_codename', 'ro.build.version.codename'),
                                ('actual_android_build_fingerprint', 'ro.build.fingerprint')):
        environment[name] = run([adb, 'shell', 'getprop', property_name], capture=True).strip()
    environment['actual_android_sdk'] = int(environment['actual_android_sdk'])
    source_properties = output / 'emulator-image-source-properties.txt'
    if source_properties.is_file():
        environment['installed_system_image_properties'] = dict(line.split('=', 1) for line in
            source_properties.read_text(encoding='utf-8').splitlines() if '=' in line and not line.startswith('#'))
    launch_config = output / 'emulator-launch-config.txt'
    if launch_config.is_file():
        environment['requested_emulator_graphics'] = launch_config.read_text(encoding='utf-8').strip()
        requested_ram = re.search(r'\bguest_ram_mb=(\d+)\b', environment['requested_emulator_graphics'])
        if requested_ram:
            environment['requested_guest_ram_mb'] = int(requested_ram.group(1))
    initial_memory = run([adb, 'shell', 'cat', '/proc/meminfo'], capture=True, timeout=30)
    actual_ram = re.search(r'^MemTotal:\s*(\d+)\s+kB\s*$', initial_memory, re.MULTILINE)
    environment['actual_guest_memtotal_kib'] = int(actual_ram.group(1)) if actual_ram else None
    emulator_log = output / 'emulator.log'
    if emulator_log.is_file():
        environment['observed_emulator_graphics'] = [line.strip() for line in emulator_log.read_text(encoding='utf-8').splitlines()
            if any(marker in line for marker in ('emuglConfig_init:', 'Graphics Adapter ', 'Graphics API Version '))]
    graphics = run([adb, 'shell', 'dumpsys', 'SurfaceFlinger'], capture=True, timeout=30)
    environment['observed_guest_gles'] = [line.strip() for line in graphics.splitlines() if 'GLES:' in line]
    (output / 'emulator-environment.json').write_text(json.dumps(environment, indent=2) + '\n', encoding='utf-8')
    if page_size != 16384:
        raise RuntimeError(f'The native release check requires a real 16-KiB environment, got {page_size}')
    if environment['actual_android_sdk'] != 36 or environment['actual_android_codename'] != 'REL':
        raise RuntimeError('The native release check requires the stable Android16/API36 guest fixture')
    # Incremental install can report success while APK blocks are still streaming.
    # Test the normal, fully installed release package before launching Qt.
    run([adb, 'install', '--no-incremental', '-r', apk], timeout=120)
    run([adb, 'logcat', '-c'])
    run([adb, 'shell', 'am', 'force-stop', PACKAGE_ID])
    packages = run([adb, 'shell', 'cmd', 'package', 'list', 'packages', '-U', PACKAGE_ID], capture=True)
    app_uid = re.search(r'^package:' + re.escape(PACKAGE_ID) + r'\s+uid:(\d+)\s*$', packages, re.MULTILINE)
    if app_uid:
        start_android_log(adb, output / 'startup-live-logcat.txt', ['--uid=' + app_uid.group(1)])
    resolved = run([adb, 'shell', 'cmd', 'package', 'resolve-activity', '--brief', PACKAGE_ID], capture=True)
    activities = [line.strip() for line in resolved.splitlines() if line.strip().startswith(PACKAGE_ID + '/')]
    if len(activities) != 1:
        raise RuntimeError('Unable to resolve the installed Android launcher activity')
    run([adb, 'shell', 'am', 'start', '-W', '-n', activities[0]], timeout=120)
    deadline = time.monotonic() + 90
    logs = ''
    required_markers = ('GIFTFINDER_ANDROID_READY', 'GIFTFINDER_ANDROID_CHARSET_READY', 'GIFTFINDER_ANDROID_TLS_READY',
                        'GIFTFINDER_ANDROID_IMAGE_READY')
    while time.monotonic() < deadline:
        process = subprocess.run([adb, 'shell', 'pidof', PACKAGE_ID], text=True, capture_output=True)
        current_pid = process.stdout.strip().split()
        log_command = [adb, 'logcat', '-d', '-v', 'threadtime']
        if len(current_pid) == 1 and current_pid[0].isdigit():
            log_command += ['--pid', current_pid[0]]
            memory = subprocess.run([adb, 'shell', 'cat', '/proc/meminfo', '/proc/' + current_pid[0] + '/status'],
                                    text=True, capture_output=True, timeout=15)
            with (output / 'startup-memory-samples.txt').open('a', encoding='utf-8') as stream:
                stream.write(time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()) + '\n')
                stream.write(memory.stdout + memory.stderr + '\n')
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
    if 'RequestsDependencyWarning' in logs:
        raise RuntimeError('Android requests has no working charset detection dependency')
    time.sleep(5)
    pid = run([adb, 'shell', 'pidof', PACKAGE_ID], capture=True).strip()
    if not pid:
        raise RuntimeError('The Android application exited after startup')
    start_android_log(adb, output / 'native-runtime-logcat.txt', ['--pid', pid])
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
    language_swipes = main_popup_and_language_test(adb, output, pid)
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
    category_popup_draft_test(adb, output, pid)
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
    run([adb, 'shell', 'settings', 'put', 'system', 'accelerometer_rotation', '0'], timeout=15)
    run([adb, 'shell', 'settings', 'put', 'system', 'user_rotation', '1'], timeout=15)
    landscape_path = output / 'android-landscape.png'
    landscape = QImage()
    landscape_colors = set()
    for _ in range(20):
        time.sleep(1)
        with landscape_path.open('wb') as stream:
            subprocess.run([adb, 'exec-out', 'screencap', '-p'], check=True, stdout=stream, timeout=20)
        landscape = QImage(str(landscape_path))
        if not landscape.isNull() and landscape.width() > landscape.height():
            landscape_colors = {landscape.pixelColor(x, y).rgba()
                                for x in range(0, landscape.width(), 17)
                                for y in range(0, landscape.height(), 19)}
            if len(landscape_colors) >= 16:
                break
    if landscape.isNull() or landscape.width() <= landscape.height() or len(landscape_colors) < 16:
        raise RuntimeError('The Android viewport did not paint its interface in landscape')
    rotated_pid = run([adb, 'shell', 'pidof', PACKAGE_ID], capture=True).strip()
    if rotated_pid != pid:
        raise RuntimeError('Rotating the Android viewport stopped or restarted the application')
    rotated_logs = run([adb, 'logcat', '-d', '--pid', pid, '-v', 'threadtime'], capture=True)
    (output / 'application-logcat.txt').write_text(rotated_logs, encoding='utf-8')
    if any(marker in rotated_logs for marker in ('FATAL EXCEPTION', 'Fatal Python error:', 'Traceback (most recent call last):')):
        raise RuntimeError('Crash detected after rotating the mobile viewport')
    run([adb, 'shell', 'uiautomator', 'dump', '/sdcard/giftfinder-landscape.xml'], timeout=45)
    landscape_hierarchy = run([adb, 'exec-out', 'cat', '/sdcard/giftfinder-landscape.xml'], capture=True)
    (output / 'landscape-accessibility.xml').write_text(landscape_hierarchy, encoding='utf-8')
    landscape_filters = next((node for node in ET.fromstring(landscape_hierarchy).iter('node')
                              if node.get('text') == 'Filters' or node.get('content-desc') == 'Filters'), None)
    landscape_bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',
                                   landscape_filters.get('bounds', '') if landscape_filters is not None else '')
    if not landscape_bounds:
        raise RuntimeError('The rotated Android interface has no accessible Filters button')
    lx1, ly1, lx2, ly2 = map(int, landscape_bounds.groups())
    if not (0 <= lx1 < lx2 <= landscape.width() and 0 <= ly1 < ly2 <= landscape.height()):
        raise RuntimeError('The rotated Android Filters button is outside its viewport')
    csv_picker_test(adb, output, pid)
    evidence = {'apk': apk.name, 'package_id': PACKAGE_ID, 'emulator_architecture': 'x86_64',
                'ready_marker_seen': True, 'process_alive_after_startup': True,
                'actual_android_page_size': page_size, 'charset_detector_runtime_check': True,
                'actual_android_sdk': environment['actual_android_sdk'],
                'actual_android_release': environment['actual_android_release'],
                'graphics_environment': environment,
                'ci_https_image_probe': smoke_probe_metadata(),
                'actions_popup_one_back_kept_main_alive': True,
                'category_popup_one_back_preserved_filter_and_draft': True,
                'language_finger_swipes_reached_japanese': True, 'language_swipes_injected': language_swipes,
                'language_normal_tap_selected_japanese_and_restored_english': True,
                'python_ssl_and_sqlite_runtime_checks': True, 'qt_ssl_backend_runtime_check': True,
                'uncached_public_image_loaded_over_https': True,
                'accessible_filters_button_tapped': True, 'mobile_filters_sheet_opened': True,
                'filters_closed_by_system_back': True, 'process_alive_after_filter_back': True,
                'soft_keyboard_was_visible': ime_was_visible, 'system_back_presses_including_keyboard_dismissal': back_presses,
                'landscape_rotation_kept_application_running': True,
                'landscape_screenshot_size': [landscape.width(), landscape.height()],
                'landscape_sampled_colors': len(landscape_colors), 'landscape_filters_button_inside_viewport': True,
                'native_csv_document_picker_opened': True, 'native_csv_content_uri_written_and_read_back': True,
                'csv_export_uses_explicit_synthetic_smoke_offer': True,
                'no_python_crash_in_application_log': True, 'screenshot_size': [image.width(), image.height()],
                'sampled_colors': len(colors), 'offline_smoke_package': True,
                'physical_arm64_device_tested': False, 'live_marketplace_search_tested': False}
    (output / 'emulator-verification.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, indent=2), flush=True)


def capture_emulator_failure(args):
    """Keep the actual failed frame and Android state without masking the failure."""
    adb = shutil.which('adb')
    if not adb:
        return
    output = Path(args.evidence).resolve()
    output.mkdir(parents=True, exist_ok=True)
    captures = {
        'android-runtime-failure.png': ['exec-out', 'screencap', '-p'],
        'runtime-failure-activities.txt': ['shell', 'dumpsys', 'activity', 'activities'],
        'runtime-failure-windows.txt': ['shell', 'dumpsys', 'window', 'windows'],
        'runtime-failure-input-method.txt': ['shell', 'dumpsys', 'input_method'],
        'runtime-failure-pid.txt': ['shell', 'pidof', PACKAGE_ID],
    }
    for filename, command in captures.items():
        try:
            with (output / filename).open('wb') as stream:
                subprocess.run([adb, *command], stdout=stream, stderr=subprocess.STDOUT, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError) as error:
            print('Could not capture Android failure evidence:', filename, type(error).__name__, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    package = commands.add_parser('build')
    package.add_argument('--arch', choices=ARCHITECTURES, required=True)
    package.add_argument('--sdk')
    package.add_argument('--ndk')
    package.add_argument('--smoke', action='store_true')
    commands.add_parser('cache-key')
    commands.add_parser('host-requirements')
    emulator = commands.add_parser('emulator-test')
    emulator.add_argument('--apk', required=True)
    emulator.add_argument('--evidence', default='build/android/x86_64/emulator')
    args = parser.parse_args()
    if args.command == 'cache-key':
        print(build_fingerprint())
    elif args.command == 'host-requirements':
        print('\n'.join(name + '==' + value for name, value in INPUTS['host_tools'].items()))
    elif args.command == 'build':
        build(args)
    else:
        try:
            emulator_test(args)
        except Exception:
            try:
                capture_emulator_failure(args)
            except Exception as error:
                print('Could not save Android failure evidence:', type(error).__name__, flush=True)
            raise


if __name__ == '__main__':
    main()
