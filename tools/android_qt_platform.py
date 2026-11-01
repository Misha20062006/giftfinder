"""Build-only, pinned Qt Android accessibility and surface lifecycle backports."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import tarfile
import tempfile
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


def patch_surface_lifecycle(source_root, specification, project_root):
    source_root, project_root = Path(source_root), Path(project_root)
    patch = project_root / specification['patch']
    if hashlib.sha256(patch.read_bytes()).hexdigest() != specification['patch_sha256']:
        raise RuntimeError('Qt lifecycle backport patch checksum differs from its pinned input')
    states = []
    for name, pins in specification['files'].items():
        path = source_root / name
        if not path.resolve().is_relative_to(source_root.resolve()):
            raise RuntimeError('Qt lifecycle source path escapes the pinned source tree')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest not in (pins['original_sha256'], pins['patched_sha256']):
            raise RuntimeError('Qt lifecycle source differs from the pinned release: ' + name)
        states.append(digest == pins['patched_sha256'])
    if all(states): return
    if any(states): raise RuntimeError('Qt lifecycle source tree contains a partial backport')
    # The extracted Qt tree may live below the application's Git checkout.
    # Stop Git discovery at its parent so paths stay relative to the Qt tree.
    env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(source_root.resolve().parent)}
    command = ['git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf', 'apply', '--whitespace=nowarn']
    subprocess.run([*command, '--check', str(patch.resolve())], cwd=source_root, env=env, check=True)
    subprocess.run([*command, str(patch.resolve())], cwd=source_root, env=env, check=True)
    for name, pins in specification['files'].items():
        if hashlib.sha256((source_root / name).read_bytes()).hexdigest() != pins['patched_sha256']:
            raise RuntimeError('Patched Qt lifecycle source failed verification: ' + name)


def replace_jar_classes(original, classes, owners):
    """Replace complete class families, including obsolete anonymous inner classes."""
    def replaced(name):
        return name.endswith('.class') and name[:-6].split('$', 1)[0] in owners
    if not all(owner + '.class' in classes for owner in owners):
        raise RuntimeError('Qt lifecycle Java compilation omitted a required class')
    if any(not replaced(name) for name in classes):
        raise RuntimeError('Qt lifecycle Java compilation produced an unrelated class')
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as target:
        for entry in source.infolist():
            if entry.filename.startswith('META-INF/') and entry.filename.endswith(('.SF', '.RSA', '.DSA')):
                raise RuntimeError('Unexpected signature in the pinned Qt Java archive')
            if not replaced(entry.filename): target.writestr(entry, source.read(entry))
        for name, payload in sorted(classes.items()):
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            target.writestr(entry, payload)
    return output.getvalue()


def rebuild_surface_java(source_root, specification, sdk, wheel, directory, environment):
    directory = Path(directory) / 'java'
    original_directory = directory / 'original'
    original_directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if name.startswith('PySide6/jar/') and name.endswith('.jar')]
        original_name = 'PySide6/jar/Qt6Android.jar'
        if original_name not in names: raise RuntimeError('The pinned Qt wheel has no Android Java archive')
        original = archive.read(original_name)
        for name in names: (original_directory / Path(name).name).write_bytes(archive.read(name))
    bootclasspath = Path(sdk) / 'platforms/android-35/android.jar'
    if not bootclasspath.is_file(): raise RuntimeError('Android API 35 Java stubs are missing')
    lambda_stubs = Path(sdk) / 'build-tools/35.0.0/core-lambda-stubs.jar'
    if not lambda_stubs.is_file(): raise RuntimeError('Android build-tools 35 Java lambda stubs are missing')
    sources = [Path(source_root) / name for name in specification['java_sources']]
    owners = {name.split('/src/', 1)[1].removesuffix('.java') for name in specification['java_sources']}
    classpath = os.pathsep.join(str(path) for path in sorted(original_directory.glob('*.jar')))
    with tempfile.TemporaryDirectory(prefix='classes-', dir=directory) as temporary:
        output = Path(temporary)
        subprocess.run(['javac', '-encoding', 'UTF-8', '-source', '8', '-target', '8',
                        '-bootclasspath', os.pathsep.join(map(str, (bootclasspath, lambda_stubs))), '-classpath', classpath,
                        '-d', str(output), *map(str, sources)], env=environment, check=True)
        classes = {path.relative_to(output).as_posix():path.read_bytes() for path in output.rglob('*.class')}
        if any(payload[:4] != b'\xca\xfe\xba\xbe' or struct.unpack_from('>H', payload, 6)[0] != 52 for payload in classes.values()):
            raise RuntimeError('Rebuilt Qt classes do not target Java 8')
        payload = replace_jar_classes(original, classes, owners)
    jar = directory / 'Qt6Android.jar'
    jar.write_bytes(payload)
    return {'jar':str(jar), 'wheel_path':original_name,
            'original_sha256':hashlib.sha256(original).hexdigest(),
            'sha256':hashlib.sha256(payload).hexdigest(),
            'classes':{name:hashlib.sha256(data).hexdigest() for name,data in classes.items()},
            'java_target':8}


def dex_native_methods(data, owner):
    """Read actual native declarations, rather than just strings in a DEX file."""
    if len(data) < 112 or not data.startswith(b'dex\n'):
        raise RuntimeError('Invalid Android DEX header')
    def u32(offset): return struct.unpack_from('<I', data, offset)[0]
    def leb(offset):
        value = shift = 0
        while True:
            byte = data[offset]; offset += 1
            value |= (byte & 127) << shift
            if byte < 128: return value, offset
            shift += 7
            if shift >= 35: raise RuntimeError('Invalid DEX variable integer')
    strings = []
    for index in range(u32(56)):
        _, offset = leb(u32(u32(60) + index * 4))
        end = data.index(0, offset)
        strings.append(data[offset:end].decode('utf-8', errors='replace'))
    types = [strings[u32(u32(68) + index * 4)] for index in range(u32(64))]
    prototypes = []
    for index in range(u32(72)):
        _, result, parameters = struct.unpack_from('<III', data, u32(76) + index * 12)
        arguments = [] if not parameters else [types[struct.unpack_from('<H', data, parameters + 4 + i * 2)[0]] for i in range(u32(parameters))]
        prototypes.append('(' + ''.join(arguments) + ')' + types[result])
    methods = []
    for index in range(u32(88)):
        class_index, prototype, name = struct.unpack_from('<HHI', data, u32(92) + index * 8)
        methods.append((types[class_index], strings[name], prototypes[prototype]))
    native = set()
    for index in range(u32(96)):
        offset = u32(100) + index * 32
        if types[u32(offset)] != owner: continue
        offset = u32(offset + 24)
        if not offset: continue
        counts = []
        for _ in range(4):
            count, offset = leb(offset); counts.append(count)
        for _ in range(counts[0] + counts[1]):
            _, offset = leb(offset); _, offset = leb(offset)
        for count in counts[2:]:
            method_index = 0
            for _ in range(count):
                delta, offset = leb(offset); method_index += delta
                flags, offset = leb(offset); _, offset = leb(offset)
                if flags & 0x100: native.add(methods[method_index][1:])
    return native


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
    lifecycle = specification['surface_lifecycle']
    patch_surface_lifecycle(source_root, lifecycle, project_root)
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
    java = rebuild_surface_java(source_root, lifecycle, sdk, wheel, base, env)
    java['jar'] = str(Path(java['jar']).relative_to(directory))
    metadata = {'qt_version': inputs['qt_version'], 'architecture': architecture,
                'upstream_fix_commit': specification['upstream_fix_commit'],
                'source_archive_sha256': source_entry['sha256'],
                'source_file': specification['source_file'],
                'original_file_sha256': specification['original_file_sha256'],
                'patched_file_sha256': specification['patched_file_sha256'],
                'patch_scope': 'accessibility guard and approved surface lifecycle backport with matching Java classes',
                'surface_lifecycle_commit': lifecycle['upstream_commit'],
                'surface_lifecycle_patch_sha256': lifecycle['patch_sha256'],
                'surface_lifecycle_files': lifecycle['files'],
                'surface_java': java,
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
    if 'surface_java' in metadata:
        java = metadata['surface_java']
        jar = directory / java['jar']
        if not jar.resolve().is_relative_to(directory.resolve()) or hashlib.sha256(jar.read_bytes()).hexdigest() != java['sha256']:
            raise RuntimeError('Prepared Qt lifecycle Java archive failed verification')
        for root in (Path(ctx.get_python_install_dir(architecture)), bundle):
            target = root / java['wheel_path']
            if not target.is_file(): raise RuntimeError('Original Qt Java archive is missing from the Python installation')
            shutil.copy2(jar, target)


def verify_packaged_platform(apk, architecture, metadata):
    name = f'libplugins_platforms_qtforandroid_{architecture}.so'
    copies = []; jars = []
    for path, payload in archive_members(Path(apk).read_bytes()):
        if path.rsplit('/', 1)[-1] == name:
            if hashlib.sha256(payload).hexdigest() != metadata['sha256']:
                raise RuntimeError('APK contains a stale or different Qt Android platform plugin: ' + path)
            copies.append(path)
        if 'surface_java' in metadata and path.endswith('/Qt6Android.jar'):
            if hashlib.sha256(payload).hexdigest() != metadata['surface_java']['sha256']:
                raise RuntimeError('APK contains a stale Qt lifecycle Java archive: ' + path)
            jars.append(path)
    if f'lib/{architecture}/{name}' not in copies or not any('_python_bundle/' in p for p in copies):
        raise RuntimeError('The rebuilt Qt Android plugin is missing from native or Python bundle contents')
    result = {**metadata, 'packaged_plugin_copies': copies, 'all_packaged_copies_match_rebuilt_plugin': True}
    if 'surface_java' in metadata:
        if not any('_python_bundle/' in path for path in jars):
            raise RuntimeError('Rebuilt Qt lifecycle Java archive is missing from the Python bundle')
        declarations = set()
        with zipfile.ZipFile(apk) as archive:
            for name in archive.namelist():
                if name.startswith('classes') and name.endswith('.dex') and '/' not in name:
                    declarations.update(dex_native_methods(archive.read(name), 'Lorg/qtproject/qt/android/QtWindow;'))
        expected = {('surfaceCreated', '(ILandroid/view/Surface;)V'),
                    ('surfaceRedrawNeeded', '(ILjava/lang/Runnable;)V'),
                    ('surfaceDestroyed', '(ILjava/lang/Runnable;)V')}
        if not expected <= declarations or any(name == 'setSurface' for name, _ in declarations):
            raise RuntimeError('APK DEX has stale or incompatible Qt lifecycle JNI declarations')
        result.update(packaged_java_copies=jars, all_packaged_java_copies_match=True,
                      lifecycle_jni_declarations_verified=True)
    return result
