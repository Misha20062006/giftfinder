"""Explicit, checksum-verified updates from this project's GitHub releases."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

import requests

from . import __version__
from .network import TIMEOUT, USER_AGENT

REPOSITORY = 'Misha20062006/giftfinder'
API = f'https://api.github.com/repos/{REPOSITORY}/releases'
PREFIX = f'https://github.com/{REPOSITORY}/releases/download/'


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('Invalid application version')
    return tuple(map(int, value.split('.')))


def target_suffix(system=None, machine=None, package_format=None):
    system = system or ('android' if hasattr(sys, 'getandroidapilevel') or 'ANDROID_ARGUMENT' in os.environ else sys.platform)
    machine = (machine or platform.machine()).lower()
    if system == 'android':
        return 'Android-arm64-v8a.apk'
    if system == 'win32':
        return 'Windows-x64-Setup.exe'
    architecture = {'aarch64': 'arm64', 'arm64': 'arm64', 'amd64': 'x64', 'x86_64': 'x64'}.get(machine)
    if not architecture:
        raise ValueError('Unsupported update architecture')
    if system == 'darwin':
        return f'macOS-{architecture}.pkg'
    if system.startswith('linux'):
        if package_format is None:
            marker = Path(sys.executable).parent / 'package-format.json'
            try:
                import json
                package_format = json.loads(marker.read_text())['format']
            except (OSError, ValueError, KeyError):
                package_format = 'deb' if Path('/etc/debian_version').exists() else 'rpm'
        if package_format not in ('deb', 'rpm'):
            raise ValueError('Unknown Linux package format')
        return f'Linux-{architecture}.{package_format}'
    raise ValueError('Unsupported update platform')


@dataclass(frozen=True)
class Release:
    version: str
    name: str
    url: str
    sha256: str
    size: int


def select_release(releases, suffix, current=__version__):
    candidates = []
    for release in releases:
        tag = release.get('tag_name', '')
        match = re.fullmatch(r'v(\d+\.\d+\.\d+)' + (r'-android\.\d+' if suffix.startswith('Android-') else ''), tag)
        if not match or release.get('draft') or (release.get('prerelease') and not suffix.startswith('Android-')):
            continue
        version = match[1]
        if version_tuple(version) <= version_tuple(current):
            continue
        expected = f'GiftFinder-{version}-{suffix}'
        assets = [asset for asset in release.get('assets', []) if asset.get('name') == expected]
        if len(assets) != 1:
            continue
        asset = assets[0]
        digest = asset.get('digest', '')
        url = asset.get('browser_download_url', '')
        size = asset.get('size')
        if (url != PREFIX + tag + '/' + expected or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest)
                or not isinstance(size, int) or isinstance(size, bool) or size <= 0):
            raise ValueError('Invalid GitHub update asset')
        candidates.append(Release(version, expected, url, digest[7:], size))
    return max(candidates, key=lambda item: version_tuple(item.version), default=None)


def check_release(suffix=None):
    response = requests.get(API, params={'per_page': 100}, timeout=TIMEOUT,
                            headers={'User-Agent': USER_AGENT, 'Accept': 'application/vnd.github+json'})
    response.raise_for_status()
    releases = response.json()
    if not isinstance(releases, list):
        raise ValueError('Invalid GitHub release list')
    return select_release(releases, suffix or target_suffix())


def download_release(release, directory, progress=lambda _: None, cancelled=lambda: False):
    if Path(release.name).name != release.name or not re.fullmatch(r'GiftFinder-[A-Za-z0-9._-]+', release.name):
        raise ValueError('Invalid installer name')
    if not release.url.startswith(PREFIX) or not re.fullmatch(r'[0-9a-f]{64}', release.sha256):
        raise ValueError('Invalid installer source')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / release.name
    descriptor, filename = tempfile.mkstemp(prefix=release.name + '-', suffix='.part', dir=directory)
    os.close(descriptor)
    temporary = Path(filename)
    digest = hashlib.sha256()
    count = 0
    try:
        with requests.get(release.url, stream=True, timeout=TIMEOUT,
                          headers={'User-Agent': USER_AGENT}) as response:
            response.raise_for_status()
            # GitHub's signed release-asset redirect remains HTTPS.
            if urlparse(response.url).scheme != 'https':
                raise ValueError('Installer download lost HTTPS')
            with temporary.open('wb') as stream:
                for chunk in response.iter_content(1024 * 256):
                    if cancelled():
                        raise InterruptedError('Update cancelled')
                    if not chunk:
                        continue
                    count += len(chunk)
                    if count > release.size:
                        raise ValueError('Installer size mismatch')
                    stream.write(chunk)
                    digest.update(chunk)
                    progress(count * 100 // release.size)
        if cancelled():
            raise InterruptedError('Update cancelled')
        if count != release.size or digest.hexdigest() != release.sha256:
            raise ValueError('Installer checksum mismatch')
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def launch_installer(path):
    path = Path(path).resolve(strict=True)
    if sys.platform == 'win32':
        # The approved Update action closes this instance; Inno starts the new one.
        subprocess.Popen([str(path), '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/UPDATE'],
                         close_fds=True)
        return True
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
