"""Build, smoke-test and package on the target OS; never reads user profiles."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def target_name(system=None, machine=None):
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine)
    if arch is None:
        raise ValueError(f'Unsupported architecture: {machine}')
    if system == 'win32':
        return f'Windows-{arch}'
    if system == 'darwin':
        return f'macOS-{arch}'
    if system.startswith('linux'):
        return f'Linux-{arch}'
    raise ValueError(f'Unsupported build platform: {system}')


def run(*command, env=None):
    subprocess.run([str(value) for value in command], cwd=ROOT, env=env, check=True)


def make_macos_icon():
    iconset = ROOT / 'build' / 'GiftFinder.iconset'
    iconset.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'giftfinder' / 'icon.png'
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
            run('sips', '-z', size * scale, size * scale, source, '--out', iconset / name)
    run('iconutil', '-c', 'icns', iconset, '-o', ROOT / 'build' / 'GiftFinder.icns')


def add_documentation(stage):
    for name in ('README.md', 'UNLICENSE', 'THIRD_PARTY_NOTICES.txt'):
        shutil.copy2(ROOT / name, stage / name)
    shutil.copytree(ROOT / 'third-party', stage / 'third-party', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'docs', stage / 'docs', dirs_exist_ok=True)
    # Keep README images and technical links usable inside the downloaded package.
    (stage / 'giftfinder').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'giftfinder' / 'icon.png', stage / 'giftfinder' / 'icon.png')
    shutil.copy2(ROOT / 'SEARCH_TECHNICAL.txt', stage / 'SEARCH_TECHNICAL.txt')


def write_zip(stage, destination):
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(stage.rglob('*')):
            if source.is_file():
                archive.write(source, source.relative_to(stage))


def write_checksums(paths, destination):
    lines = []
    for path in sorted(paths):
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        lines.append(f'{digest}  {path.name}\n')
    destination.write_text(''.join(lines), encoding='utf-8')


def package_artifacts(dist, executable, output, build, version, target):
    """Use a fresh staging directory; an earlier package cannot add stale files."""
    prefix = f'GiftFinder-{version}-{target}'
    build.mkdir(parents=True, exist_ok=True)
    artifacts = []
    with tempfile.TemporaryDirectory(prefix='package-', dir=build) as temporary:
        stage = Path(temporary)
        if stage.resolve().parent != build.resolve():
            raise RuntimeError('Package staging escaped its managed build directory')
        add_documentation(stage)
        if target.startswith('Windows-'):
            shutil.copy2(executable, stage / 'GiftFinder.exe')
            standalone = output / f'{prefix}.exe'
            shutil.copy2(executable, standalone)
            artifacts.append(standalone)
            archive = output / f'{prefix}.zip'
            write_zip(stage, archive)
        elif target.startswith('macOS-'):
            shutil.copytree(dist / 'GiftFinder.app', stage / 'GiftFinder.app', symlinks=True)
            (stage / 'Applications').symlink_to('/Applications', target_is_directory=True)
            archive = output / f'{prefix}.dmg'
            run('hdiutil', 'create', '-volname', 'GiftFinder', '-srcfolder', stage,
                '-ov', '-format', 'UDZO', archive)
        else:
            shutil.copytree(dist / 'GiftFinder', stage / 'GiftFinder', symlinks=True)
            (stage / 'start-giftfinder.sh').write_text(
                '#!/bin/sh\ncd -- "$(dirname -- "$0")" || exit 1\nexec ./GiftFinder/GiftFinder "$@"\n', encoding='utf-8')
            (stage / 'start-giftfinder.sh').chmod(0o755)
            archive = output / f'{prefix}.tar.gz'
            with tarfile.open(archive, 'w:gz') as package:
                package.add(stage, arcname='GiftFinder')
        artifacts.append(archive)
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'release-dist')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    version = runpy.run_path(str(ROOT / 'giftfinder' / '__init__.py'))['__version__']
    target = target_name()
    build = ROOT / 'build' / target
    dist = build / 'dist'
    if sys.platform == 'darwin':
        make_macos_icon()
    run(sys.executable, '-m', 'PyInstaller', ROOT / 'GiftFinder.spec',
        '--noconfirm', '--distpath', dist, '--workpath', build / 'pyinstaller')
    if sys.platform == 'win32':
        executable = dist / 'GiftFinder.exe'
    elif sys.platform == 'darwin':
        executable = dist / 'GiftFinder.app' / 'Contents' / 'MacOS' / 'GiftFinder'
    else:
        executable = dist / 'GiftFinder' / 'GiftFinder'
    profile = build / 'smoke-test'
    env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
           'GIFT_FINDER_DATA_DIR': str(profile / 'profile')}
    run(executable, '--smoke-test', profile, env=env)
    assert (profile / 'result.txt').read_text(encoding='utf-8').startswith('PASS:')
    artifacts = package_artifacts(dist, executable, output, build, version, target)
    write_checksums(artifacts, output / f'SHA256-{target}.txt')
    (build / 'verification.json').write_text(json.dumps({
        'version': version, 'target': target, 'system': platform.platform(),
        'python': platform.python_version(), 'smoke_test': 'passed',
        'artifacts': [path.name for path in artifacts]}, indent=2), encoding='utf-8')
    print(f'Packaged and smoke-tested {target}: ' + ', '.join(path.name for path in artifacts))


if __name__ == '__main__':
    main()
