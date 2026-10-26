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


def test_repeated_package_omits_removed_files_and_does_not_clean_existing_directories(tmp_path, monkeypatch):
    build = tmp_path / 'build'
    dist = build / 'dist'
    bundle = dist / 'GiftFinder'
    bundle.mkdir(parents=True)
    executable = bundle / 'GiftFinder'
    executable.write_bytes(b'current executable')
    removed = bundle / 'removed.so'
    removed.write_bytes(b'old dependency')
    legacy = build / 'package'
    legacy.mkdir()
    (legacy / 'keep-existing-artifact.txt').write_text('untouched', encoding='utf-8')
    output = tmp_path / 'releases'
    output.mkdir()
    monkeypatch.setattr(builder, 'add_documentation', lambda stage: (stage / 'README.md').write_text('current docs', encoding='utf-8'))

    archive, = builder.package_artifacts(dist, executable, output, build, '0.7.1', 'Linux-x64')
    with tarfile.open(archive) as package:
        assert 'GiftFinder/GiftFinder/removed.so' in package.getnames()
    removed.unlink()
    builder.package_artifacts(dist, executable, output, build, '0.7.1', 'Linux-x64')
    with tarfile.open(archive) as package:
        assert 'GiftFinder/GiftFinder/removed.so' not in package.getnames()
        assert package.extractfile('GiftFinder/GiftFinder/GiftFinder').read() == b'current executable'
        assert 'GiftFinder/README.md' in package.getnames()
    assert (legacy / 'keep-existing-artifact.txt').read_text(encoding='utf-8') == 'untouched'
    assert not list(build.glob('package-*'))
