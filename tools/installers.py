"""Native system installers. User profiles are never part of the payload."""
from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([str(value) for value in args], check=True)


def windows(stage, output, version):
    compiler = os.environ.get('ISCC_EXE') or shutil.which('ISCC.exe')
    if not compiler:
        raise RuntimeError('Set ISCC_EXE to the Inno Setup compiler')
    run(compiler, '/DAppVersion=' + version, '/DPayload=' + str(stage),
        '/DOutputDir=' + str(output), '/DSourceRoot=' + str(ROOT), ROOT / 'packaging/windows.iss')
    return output / f'GiftFinder-{version}-Windows-x64-Setup.exe'


def macos(stage, output, version, target, work):
    payload = work / 'macos-root'
    app = payload / 'Applications/GiftFinder.app'
    app.parent.mkdir(parents=True)
    shutil.copytree(stage / 'GiftFinder.app', app, symlinks=True)
    components = work / 'components.plist'
    with components.open('wb') as stream:
        plistlib.dump([{'RootRelativeBundlePath': 'Applications/GiftFinder.app',
                       'BundleIsRelocatable': False, 'BundleIsVersionChecked': True,
                       'BundleHasStrictIdentifier': True, 'BundleOverwriteAction': 'upgrade'}], stream)
    destination = output / f'GiftFinder-{version}-{target}.pkg'
    run('pkgbuild', '--root', payload, '--component-plist', components,
        '--identifier', 'io.github.Misha20062006.giftfinder', '--version', version,
        '--install-location', '/', destination)
    return destination


def linux_payload(stage, work, package_format):
    payload = work / (package_format + '-root')
    app = payload / 'opt/giftfinder'
    app.parent.mkdir(parents=True)
    shutil.copytree(stage / 'GiftFinder', app, symlinks=True)
    (app / 'package-format.json').write_text(json.dumps({'format': package_format}), encoding='utf-8')
    executable = app / 'GiftFinder'
    executable.chmod(0o755)
    binary = payload / 'usr/bin/giftfinder'
    binary.parent.mkdir(parents=True)
    binary.symlink_to('/opt/giftfinder/GiftFinder')
    desktop = payload / 'usr/share/applications/giftfinder.desktop'
    desktop.parent.mkdir(parents=True)
    desktop.write_text('[Desktop Entry]\nType=Application\nName=GiftFinder\n'
                       'Comment=Find Telegram gifts and compare marketplace offers\n'
                       'Exec=/opt/giftfinder/GiftFinder\nIcon=giftfinder\nTerminal=false\n'
                       'Categories=Utility;Network;\nStartupWMClass=GiftFinder\n', encoding='utf-8')
    icon = payload / 'usr/share/icons/hicolor/256x256/apps/giftfinder.png'
    icon.parent.mkdir(parents=True)
    shutil.copy2(ROOT / 'giftfinder/icon.png', icon)
    documentation = payload / 'usr/share/doc/giftfinder'
    documentation.mkdir(parents=True)
    for name in ('UNLICENSE', 'THIRD_PARTY_NOTICES.txt'):
        shutil.copy2(ROOT / name, documentation / name)
    return payload


def linux(stage, output, version, target, work):
    architecture = 'arm64' if target.endswith('arm64') else 'amd64'
    minimum = '2.39' if architecture == 'arm64' else '2.35'
    payload = linux_payload(stage, work, 'deb')
    control = payload / 'DEBIAN'
    control.mkdir()
    (control / 'control').write_text(
        f'Package: giftfinder\nVersion: {version}\nArchitecture: {architecture}\n'
        'Maintainer: Misha20062006 <Misha20062006@users.noreply.github.com>\n'
        f'Depends: libc6 (>= {minimum}), libegl1, libopengl0, libxkbcommon-x11-0, '
        'libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, '
        'libxcb-xinerama0, libxcb-randr0, libxcb-shape0\n'
        'Section: utils\nPriority: optional\nHomepage: https://github.com/Misha20062006/giftfinder\n'
        'Description: Search Telegram gifts and compare marketplace offers\n', encoding='utf-8')
    control.chmod(0o755)
    (control / 'control').chmod(0o644)
    deb = output / f'GiftFinder-{version}-{target}.deb'
    run('dpkg-deb', '--root-owner-group', '--build', payload, deb)
    rpm_payload = linux_payload(stage, work, 'rpm')
    rpm_top = work / 'rpmbuild'
    for name in ('BUILD', 'BUILDROOT', 'RPMS', 'SOURCES', 'SPECS', 'SRPMS'):
        (rpm_top / name).mkdir(parents=True)
    rpm_arch = 'aarch64' if architecture == 'arm64' else 'x86_64'
    specification = rpm_top / 'SPECS/giftfinder.spec'
    specification.write_text(
        f'Name: giftfinder\nVersion: {version}\nRelease: 1\nSummary: Telegram gift search\n'
        'License: Unlicense AND LGPL-3.0-only\nURL: https://github.com/Misha20062006/giftfinder\n'
        f'BuildArch: {rpm_arch}\nAutoReqProv: no\nRequires: glibc >= {minimum}\n'
        'Requires: libstdc++, libglvnd-egl, libglvnd-opengl, libxkbcommon-x11, xcb-util-cursor, '
        'xcb-util-wm, xcb-util-image, xcb-util-keysyms, xcb-util-renderutil, libxcb\n'
        '%description\nFind Telegram gifts and compare marketplace offers.\n'
        '%prep\n%build\n%install\n'
        f'mkdir -p "%{{buildroot}}"\ncp -a "{rpm_payload}/." "%{{buildroot}}/"\n'
        '%files\n/opt/giftfinder\n/usr/bin/giftfinder\n/usr/share/applications/giftfinder.desktop\n'
        '/usr/share/icons/hicolor/256x256/apps/giftfinder.png\n/usr/share/doc/giftfinder\n', encoding='utf-8')
    run('rpmbuild', '--define', '_topdir ' + str(rpm_top), '--define', '_build_id_links none',
        '--define', '__os_install_post %{nil}', '-bb', specification)
    candidates = list((rpm_top / 'RPMS').rglob('*.rpm'))
    if len(candidates) != 1:
        raise RuntimeError('Expected one RPM installer')
    rpm = output / f'GiftFinder-{version}-{target}.rpm'
    shutil.copy2(candidates[0], rpm)
    return [deb, rpm]
