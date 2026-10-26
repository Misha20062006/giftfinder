"""Build-only Android runtime repairs from pinned universal wheels/Qt source."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile


MODULES = {'requests': 'requests', 'beautifulsoup4': 'bs4', 'urllib3': 'urllib3',
           'certifi': 'certifi', 'idna': 'idna', 'charset-normalizer': 'charset_normalizer',
           'soupsieve': 'soupsieve', 'typing_extensions': 'typing_extensions.py'}


def verified_wheel(path, expected):
    path = Path(path)
    if not path.name.endswith('-none-any.whl') or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError('A pinned universal Android dependency wheel failed verification')
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            parts = Path(item.filename).parts
            if Path(item.filename).is_absolute() or '..' in parts or any(p.endswith('.data') for p in parts):
                raise RuntimeError('Unsupported path in universal dependency wheel')
            if item.is_dir():
                continue
            head = archive.read(item)[:4]
            if head == b'\x7fELF' or head[:2] == b'MZ' or item.filename.endswith(('.so', '.pyd', '.dll', '.dylib')):
                raise RuntimeError('A supposedly pure Python wheel contains native code')


def _remove_owned(path, root):
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise RuntimeError('Unsafe path in managed Android Python installation')
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def active_distribution(toolchain):
    distribution = toolchain._dist
    # _build_package creates a new bootstrap, but p4a only attaches its selected
    # distribution in build_dist_from_args. Cached APK packaging skips that path.
    toolchain.ctx.bootstrap.distribution = distribution
    return distribution


def install_pure_dependencies(directory, wheel_directory, dependencies):
    """Replace only declared module roots; discard stale host accelerators entirely."""
    directory, wheel_directory = Path(directory), Path(wheel_directory)
    for dependency in dependencies:
        requirement = dependency['requirement']
        project = requirement.split('==', 1)[0]
        wheel = wheel_directory / dependency['filename']
        verified_wheel(wheel, dependency['sha256'])
        _remove_owned(directory / MODULES[project], directory)
        normalized = project.replace('-', '_').casefold()
        for metadata in directory.glob('*.dist-info'):
            name = metadata.name.removesuffix('.dist-info').rsplit('-', 1)[0]
            if name.replace('-', '_').casefold() == normalized:
                _remove_owned(metadata, directory)
        with zipfile.ZipFile(wheel) as archive:
            for item in archive.infolist():
                destination = directory / item.filename
                if not destination.resolve().is_relative_to(directory.resolve()):
                    raise RuntimeError('Universal wheel path escapes Android site-packages')
            archive.extractall(directory)


def rebuild_shiboken(toolchain, inputs_directory, inputs):
    """Compile the real generated module against this exact target Python/NDK ABI."""
    ctx = toolchain.ctx
    arch = ctx.archs[0]
    selected = active_distribution(toolchain)
    installed = Path(ctx.get_python_install_dir(arch.arch))
    distribution = Path(selected.dist_dir)
    bundled = distribution / f'_python_bundle__{arch.arch}/_python_bundle/site-packages'
    python_recipe = ctx.python_recipe
    if python_recipe is None:
        # p4a create/apk are separate processes; cached packaging has not run
        # TargetPythonRecipe.prebuild_arch, which normally sets this field.
        from pythonforandroid.recipe import Recipe
        python_recipe = Recipe.get_recipe('python3', ctx)
    python_headers = Path(python_recipe.include_root(arch.arch))
    libraries = Path(ctx.get_libs_dir(arch.arch))
    source = inputs_directory / 'source'
    generated = inputs_directory / 'generated/Shiboken'
    target = inputs_directory / ('compiled-' + arch.arch) / 'Shiboken.abi3.so'
    target.parent.mkdir(exist_ok=True)
    python_library = libraries / f'libpython{python_recipe.major_minor_version_string}.so'
    shiboken_library = libraries / 'libshiboken6.abi3.so'
    if not (python_headers / 'Python.h').is_file() or not python_library.is_file() or not shiboken_library.is_file():
        raise RuntimeError('Target Python/Shiboken headers and libraries must exist before rebuilding the module')
    command = [arch.get_clang_exe(with_target=True, plus_plus=True), *inputs['shiboken_flags'],
               '-nostdlib++', '-I' + str(python_headers),
               '-I' + str(installed / 'shiboken6/include/shiboken6'),
               '-I' + str(source / 'sources/shiboken6/libshiboken'), '-I' + str(generated),
               str(generated / 'shiboken_module_wrapper.cpp'), '-L' + str(libraries),
               '-l:libshiboken6.abi3.so', '-l:' + python_library.name,
               '-L' + str(Path(ctx.ndk.sysroot_lib_dir) / arch.command_prefix), '-lc++_shared',
               '-o', str(target)]
    print('GiftFinder: rebuilding exact Qt Shiboken wrapper for', arch.arch, flush=True)
    subprocess.run(command, check=True)
    for directory in (installed, bundled):
        destination = directory / 'shiboken6/Shiboken.abi3.so'
        if not destination.is_file():
            raise RuntimeError('Original target Shiboken module is missing from the Python installation')
        shutil.copy2(target, destination)
    return {'source_commit': inputs['shiboken_source']['commit'],
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'architecture': arch.arch}


def prepare_distribution(toolchain):
    inputs_directory = Path(os.environ['GIFT_FINDER_ANDROID_RUNTIME_INPUTS'])
    inputs = json.loads((inputs_directory / 'inputs.json').read_text(encoding='utf-8'))
    arch = toolchain.ctx.archs[0].arch
    selected = active_distribution(toolchain)
    installed = Path(toolchain.ctx.get_python_install_dir(arch))
    bundled = Path(selected.dist_dir) / f'_python_bundle__{arch}/_python_bundle/site-packages'
    for directory in (installed, bundled):
        if not directory.is_dir():
            raise RuntimeError('Android distribution has no Python site-packages directory')
        install_pure_dependencies(directory, inputs_directory / 'pure-wheels', inputs['pure_wheels'])
    rebuilt = rebuild_shiboken(toolchain, inputs_directory, inputs)
    (inputs_directory / ('rebuild-' + arch + '.json')).write_text(json.dumps(rebuilt, indent=2) + '\n', encoding='utf-8')
