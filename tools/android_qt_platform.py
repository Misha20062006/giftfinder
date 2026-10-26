"""Build-only, exact-source Qt Android accessibility backport (QTBUG-146706)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

from tools.android_elf import archive_members


def patch_accessibility(source, specification):
    source = Path(source)
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest == specification['patched_file_sha256']:
        return
    if digest != specification['original_file_sha256']:
        raise RuntimeError('Qt accessibility source differs from the pinned release')
    replacements = ((b'QAndroidPlatformWindow::surfacesCount() == 0',
                     b'QGuiApplication::topLevelWindows().isEmpty()'),
                    (b'no valid surface.', b'no top-level windows.'))
    for previous, replacement in replacements:
        if data.count(previous) != 1:
            raise RuntimeError('The official Qt accessibility backport no longer matches')
        data = data.replace(previous, replacement)
    if hashlib.sha256(data).hexdigest() != specification['patched_file_sha256']:
        raise RuntimeError('Patched Qt accessibility source failed its exact checksum')
    source.write_bytes(data)


def _extract(archive, destination, digest, environment):
    destination = Path(destination)
    marker = destination / ('.verified-' + archive.name + '.sha256')
    if marker.is_file() and marker.read_text(encoding='ascii').strip() == digest:
        return
    destination.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith('.7z'):
        subprocess.run(['7z', 'x', '-y', '-o' + str(destination), str(archive)],
                       env=environment, check=True, stdout=subprocess.DEVNULL)
    else:
        with tarfile.open(archive) as package:
            package.extractall(destination, filter='data')
    marker.write_text(digest + '\n', encoding='ascii')


def _kit_root(directory):
    configurations = list(Path(directory).rglob('lib/cmake/Qt6/Qt6Config.cmake'))
    if len(configurations) != 1:
        raise RuntimeError('The pinned Qt SDK archive has no unique Qt6 kit')
    return configurations[0].parents[3]


def prepare_platform(directory, inputs, architecture, ndk, sdk, wheel, downloader, environment, project_root):
    """Compile before p4a, so SDK/source mismatches fail before its native build."""
    directory, ndk = Path(directory), Path(ndk)
    specification = inputs['qt_android_platform']
    base = directory / 'qt-platform'
    source_entry = specification['source_archive']
    source_archive = downloader(source_entry['url'], source_entry['sha256'], base / 'downloads' / source_entry['filename'])
    _extract(source_archive, base / 'source', source_entry['sha256'], environment)
    source_root = base / 'source' / source_entry['root']
    patch_accessibility(source_root / specification['source_file'], specification)
    for label, entry in (('host', specification['host_sdk']),
                         ('target-' + architecture, specification['target_sdks'][architecture])):
        archive = downloader(entry['url'], entry['sha256'], base / 'downloads' / entry['filename'])
        _extract(archive, base / label, entry['sha256'], environment)
    host, target = _kit_root(base / 'host'), _kit_root(base / ('target-' + architecture))
    icu = specification['host_icu']
    archive = downloader(icu['url'], icu['sha256'], base / 'downloads' / icu['filename'])
    _extract(archive, host / 'lib', icu['sha256'], environment)
    # Exact same-version private headers, but resolve native symbols against the
    # libraries actually shipped in this APK, rather than another Qt build.
    with zipfile.ZipFile(wheel) as archive:
        for module in ('Core', 'Gui'):
            name = f'libQt6{module}_{architecture}.so'
            payload = archive.read('PySide6/Qt/lib/' + name)
            (target / 'lib' / name).write_bytes(payload)
    for executable in (host / 'libexec').glob('*'):
        if executable.is_file() and executable.read_bytes()[:4] == b'\x7fELF':
            executable.chmod(executable.stat().st_mode | 0o111)
    build = base / ('build-' + architecture)
    output = build / 'output'
    env = dict(environment)
    env['LD_LIBRARY_PATH'] = str(host / 'lib') + (os.pathsep + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    configure = ['cmake', '-S', str(Path(project_root) / 'mobile/qt_platform'), '-B', str(build), '-G', 'Ninja',
                 '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_TOOLCHAIN_FILE=' + str(target / 'lib/cmake/Qt6/qt.toolchain.cmake'),
                 '-DQT_HOST_PATH=' + str(host), '-DANDROID_NDK=' + str(ndk), '-DCMAKE_ANDROID_NDK=' + str(ndk),
                 '-DANDROID_NDK_ROOT=' + str(ndk), '-DANDROID_SDK_ROOT=' + str(sdk),
                 '-DQT_CHAINLOAD_TOOLCHAIN_FILE=' + str(ndk / 'build/cmake/android.toolchain.cmake'),
                 '-DANDROID_ABI=' + architecture, '-DANDROID_PLATFORM=android-' + str(inputs['minimum_api']),
                 '-DGIFTFINDER_QTBASE_SOURCE=' + str(source_root), '-DCMAKE_LIBRARY_OUTPUT_DIRECTORY=' + str(output)]
    print('GiftFinder: building exact Qt Android platform accessibility backport for', architecture, flush=True)
    subprocess.run(configure, env=env, check=True)
    subprocess.run(['cmake', '--build', str(build), '--parallel', '2'], env=env, check=True)
    plugin = output / f'libplugins_platforms_qtforandroid_{architecture}.so'
    if not plugin.is_file():
        raise RuntimeError('The rebuilt Qt Android platform plugin has an unexpected output name')
    strip = ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip'
    subprocess.run([str(strip), '--strip-unneeded', str(plugin)], env=env, check=True)
    metadata = {'qt_version': inputs['qt_version'], 'architecture': architecture,
                'upstream_fix_commit': specification['upstream_fix_commit'],
                'source_archive_sha256': source_entry['sha256'],
                'source_file': specification['source_file'],
                'original_file_sha256': specification['original_file_sha256'],
                'patched_file_sha256': specification['patched_file_sha256'],
                'patch_scope': 'official accessibility guard and diagnostic message only',
                'plugin': str(plugin.relative_to(directory)), 'sha256': hashlib.sha256(plugin.read_bytes()).hexdigest(),
                'links_against_pinned_wheel_core_and_gui': True}
    (directory / ('qt-platform-' + architecture + '.json')).write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return metadata


def install_platform(toolchain, directory):
    directory = Path(directory)
    ctx = toolchain.ctx
    architecture = ctx.archs[0].arch
    selected = toolchain._dist
    metadata = json.loads((directory / ('qt-platform-' + architecture + '.json')).read_text(encoding='utf-8'))
    source = directory / metadata['plugin']
    if not source.resolve().is_relative_to(directory.resolve()) or hashlib.sha256(source.read_bytes()).hexdigest() != metadata['sha256']:
        raise RuntimeError('Prepared Qt Android platform plugin failed verification')
    native = f'libplugins_platforms_qtforandroid_{architecture}.so'
    bundle = Path(selected.dist_dir) / f'_python_bundle__{architecture}/_python_bundle/site-packages'
    targets = [Path(ctx.get_python_install_dir(architecture)) / 'PySide6/Qt/plugins/platforms' / native,
               bundle / 'PySide6/Qt/plugins/platforms' / native,
               Path(selected.dist_dir) / 'libs' / architecture / native,
               Path(ctx.get_libs_dir(architecture)) / native]
    for target in targets:
        if not target.is_file():
            raise RuntimeError('Expected original Qt Android platform plugin is missing: ' + str(target))
        shutil.copy2(source, target)


def verify_packaged_platform(apk, architecture, metadata):
    name = f'libplugins_platforms_qtforandroid_{architecture}.so'
    copies = []
    for path, payload in archive_members(Path(apk).read_bytes()):
        if path.rsplit('/', 1)[-1] == name:
            if hashlib.sha256(payload).hexdigest() != metadata['sha256']:
                raise RuntimeError('APK contains a stale or different Qt Android platform plugin: ' + path)
            copies.append(path)
    if f'lib/{architecture}/{name}' not in copies or not any('_python_bundle/' in p for p in copies):
        raise RuntimeError('The rebuilt Qt Android plugin is missing from native or Python bundle contents')
    return {**metadata, 'packaged_plugin_copies': copies, 'all_packaged_copies_match_rebuilt_plugin': True}
