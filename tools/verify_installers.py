"""CI-only native installation/reinstallation checks with an isolated profile."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from giftfinder import __version__
from tools.build_release import target_name


def run(*command, env=None):
    subprocess.run([str(value) for value in command], check=True, env=env)


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Installer installation tests run only on disposable CI runners')
    target = target_name()
    work = ROOT / 'build' / target / 'installer-test'
    work.mkdir(parents=True, exist_ok=True)
    smoke = work / 'smoke'
    profile = smoke / 'profile'
    profile.mkdir(parents=True, exist_ok=True)
    preferences = profile / 'preferences.json'
    preferences.write_text(json.dumps({'settings': {'language':'en','installer_sentinel':'keep'},
                                       'favorites':{},'searches':[]}), encoding='utf-8')
    environment = {**os.environ, 'QT_QPA_PLATFORM':'offscreen', 'GIFT_FINDER_DATA_DIR':str(profile)}
    prefix = ROOT / 'release-dist' / f'GiftFinder-{__version__}-{target}'
    if sys.platform == 'win32':
        installer = Path(str(prefix) + '-Setup.exe')
        destination = work / 'installed'
        executable = destination / 'GiftFinder.exe'
        install = [installer, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOAUTORUN', '/NOICONS',
                   '/DIR=' + str(destination)]
    elif sys.platform == 'darwin':
        install = ['sudo', 'installer', '-pkg', str(prefix) + '.pkg', '-target', '/']
        executable = Path('/Applications/GiftFinder.app/Contents/MacOS/GiftFinder')
    else:
        install = ['sudo', 'dpkg', '--install', str(prefix) + '.deb']
        executable = Path('/opt/giftfinder/GiftFinder')
    for _ in range(2):
        run(*install)
        run(executable, '--smoke-test', smoke, env=environment)
        if json.loads(preferences.read_text(encoding='utf-8'))['settings']['installer_sentinel'] != 'keep':
            raise RuntimeError('Installation changed the existing user profile')
    checks = {'native_installation':True, 'installed_executable_smoke_test':True,
              'reinstallation_preserved_existing_profile':True}
    if sys.platform == 'win32':
        uninstaller = destination / 'unins000.exe'
        if not uninstaller.resolve().is_relative_to(work.resolve()):
            raise RuntimeError('Uninstaller escaped the CI installation directory')
        run(uninstaller, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
        if executable.exists() or not preferences.is_file():
            raise RuntimeError('Uninstall did not preserve the isolated user profile')
        checks['uninstallation_preserved_profile'] = True
    elif sys.platform.startswith('linux'):
        run('sudo', 'dpkg', '--remove', 'giftfinder')
        if executable.exists() or not preferences.is_file():
            raise RuntimeError('Uninstall did not preserve the isolated user profile')
        checks['uninstallation_preserved_profile'] = True
        # Exercise the RPM in its native package manager, not Ubuntu's database.
        rpm = Path(str(prefix) + '.rpm')
        rpm_smoke = work / 'rpm-smoke'
        rpm_smoke.mkdir()
        run('docker', 'run', '--rm', '-v', str(rpm) + ':/release/giftfinder.rpm:ro',
            '-v', str(rpm_smoke) + ':/verification', 'fedora:44', '/bin/bash', '-ec',
            'dnf install -y /release/giftfinder.rpm dejavu-sans-fonts; '
            'QT_QPA_PLATFORM=offscreen /opt/giftfinder/GiftFinder --smoke-test /verification; '
            'dnf remove -y giftfinder; test -f /verification/profile/preferences.json')
        checks['rpm_native_installation_and_runtime'] = True
    (work / 'verification.json').write_text(json.dumps(checks, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(checks), flush=True)


if __name__ == '__main__':
    main()
