"""Release portability checks that do not build or touch the normal profile."""
import importlib.util
from pathlib import Path
import tarfile
import zipfile

import pytest

spec = importlib.util.spec_from_file_location('build_release', Path(__file__).resolve().parents[1] / 'tools/build_release.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.mark.parametrize('system,machine,target', [
    ('win32', 'AMD64', 'Windows-x64'),
    ('darwin', 'arm64', 'macOS-arm64'),
    ('darwin', 'x86_64', 'macOS-x64'),
    ('linux', 'x86_64', 'Linux-x64'),
    ('linux', 'aarch64', 'Linux-arm64'),
])
def test_release_target_names(system, machine, target):
    assert builder.target_name(system, machine) == target


def test_unknown_platform_does_not_get_a_desktop_package_name():
    with pytest.raises(ValueError):
        builder.target_name('android', 'aarch64')


def test_zip_contains_only_staged_distribution_files_and_checksums_match(tmp_path):
    stage = tmp_path / 'package'
    stage.mkdir()
    (stage / 'GiftFinder.exe').write_bytes(b'packaged-binary')
    (stage / 'docs').mkdir()
    (stage / 'docs' / 'guide.md').write_text('Guide', encoding='utf-8')
    (tmp_path / 'preferences.json').write_text('private data', encoding='utf-8')
    archive = tmp_path / 'GiftFinder.zip'
    builder.write_zip(stage, archive)
    with zipfile.ZipFile(archive) as package:
        assert set(package.namelist()) == {'GiftFinder.exe', 'docs/guide.md'}
    checksums = tmp_path / 'SHA256.txt'
    builder.write_checksums([archive], checksums)
    import hashlib
    assert checksums.read_text().strip() == hashlib.sha256(archive.read_bytes()).hexdigest() + '  GiftFinder.zip'
