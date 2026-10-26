"""Inspect actual Android ELF contents, including Python bundles inside APKs."""
from __future__ import annotations

import io
from pathlib import Path
import struct
import tarfile
import zipfile


MACHINES = {'arm64-v8a': 183, 'x86_64': 62}
PAGE_SIZE = 16384
ANDROID_SYSTEM_LIBRARIES = {
    'libc.so', 'libm.so', 'libdl.so', 'liblog.so', 'libandroid.so', 'libz.so',
    'libEGL.so', 'libGLESv1_CM.so', 'libGLESv2.so', 'libGLESv3.so',
    'libOpenSLES.so', 'libOpenMAXAL.so', 'libjnigraphics.so', 'libmediandk.so',
    'libcamera2ndk.so', 'libaaudio.so', 'libvulkan.so', 'libnativewindow.so',
    'libsync.so',
}


def elf_info(data, name):
    if not data.startswith(b'\x7fELF'):
        return None
    if len(data) < 64 or data[4:6] != b'\x02\x01':
        raise RuntimeError(f'{name}: expected a little-endian 64-bit Android ELF')
    unpack = lambda fmt, offset: struct.unpack_from('<' + fmt, data, offset)
    machine = unpack('H', 18)[0]
    kind = unpack('H', 16)[0]
    phoff = unpack('Q', 32)[0]
    phsize, count = unpack('HH', 54)
    if (count and phsize < 56) or phoff + phsize * count > len(data):
        raise RuntimeError(f'{name}: invalid ELF program headers')
    segments = [unpack('IIQQQQQQ', phoff + phsize * index) for index in range(count)]
    loads = [p for p in segments if p[0] == 1]
    if not loads and kind != 1:
        raise RuntimeError(f'{name}: ELF has no LOAD segments')
    needed, soname, strings = [], None, b''
    for dynamic in (p for p in segments if p[0] == 2):
        entries = [unpack('qQ', offset) for offset in
                   range(dynamic[2], dynamic[2] + dynamic[5], 16)]
        values = {tag: value for tag, value in entries}
        if 5 not in values or 10 not in values:
            continue
        address = values[5]
        containing = next((p for p in loads if p[3] <= address < p[3] + p[5]), None)
        if containing is None:
            raise RuntimeError(f'{name}: ELF dynamic string table is not file-backed')
        offset = containing[2] + address - containing[3]
        strings = data[offset:offset + values[10]]
        def string_at(index):
            return strings[index:].split(b'\0', 1)[0].decode('utf-8')
        needed = [string_at(value) for tag, value in entries if tag == 1]
        soname = string_at(values[14]) if 14 in values else None
    interpreter = next((data[p[2]:p[2] + p[5]].rstrip(b'\0').decode('utf-8')
                        for p in segments if p[0] == 3), None)
    return {'path': name, 'machine': machine, 'kind': kind, 'needed': needed, 'soname': soname,
            'interpreter': interpreter, 'loads': loads,
            'relro': [p for p in segments if p[0] == 0x6474e552],
            'glibc_versions': [s.decode('ascii') for s in strings.split(b'\0')
                               if s.startswith((b'GLIBC_', b'GLIBCXX_'))]}


def validate_elf(info, architecture):
    name = info['path']
    if info['machine'] != MACHINES[architecture]:
        raise RuntimeError(f'{name}: foreign ELF machine {info["machine"]}; expected {MACHINES[architecture]}')
    if info['interpreter'] not in (None, '/system/bin/linker64') or info['glibc_versions']:
        raise RuntimeError(f'{name}: host operating-system ABI in Android package')
    for p in info['loads']:
        if p[7] < PAGE_SIZE or p[2] % PAGE_SIZE != p[3] % PAGE_SIZE:
            raise RuntimeError(f'{name}: LOAD segment is not genuinely 16-KiB aligned')
    # RELRO can end between page boundaries when it owns its entire LOAD segment.
    # Reject only protection that would overlap actual writable bytes outside it.
    for relro in info['relro']:
        start, end = relro[3], relro[3] + relro[6]
        protected_start = start // PAGE_SIZE * PAGE_SIZE
        protected_end = (end + PAGE_SIZE - 1) // PAGE_SIZE * PAGE_SIZE
        for load in (p for p in info['loads'] if p[1] & 2):
            left = max(load[3], protected_start)
            right = min(load[3] + load[6], protected_end)
            if left < right and (left < start or right > end):
                raise RuntimeError(f'{name}: 16-KiB RELRO protection overlaps writable data')
    return {'path': name, 'machine': info['machine'], 'needed': info['needed'],
            'minimum_load_alignment': min((p[7] for p in info['loads']), default=None),
            'relro_segments_checked': len(info['relro'])}


def archive_members(data, prefix='', depth=0):
    if depth > 8:
        raise RuntimeError('Unexpected archive nesting in Android package')
    if data.startswith((b'PK\x03\x04', b'PK\x05\x06')):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for entry in archive.infolist():
                if not entry.is_dir():
                    name = prefix + entry.filename
                    body = archive.read(entry)
                    yield name, body
                    if body.startswith((b'PK\x03\x04', b'\x1f\x8b')) or name.endswith(('.tar', 'libpybundle.so')):
                        yield from archive_members(body, name + ' :: ', depth + 1)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
            for entry in archive.getmembers():
                if entry.isfile() or entry.islnk():
                    name = prefix + entry.name
                    body = archive.extractfile(entry).read()
                    yield name, body
                    if body.startswith((b'PK\x03\x04', b'\x1f\x8b')) or name.endswith('.tar'):
                        yield from archive_members(body, name + ' :: ', depth + 1)


def audit_apk(path, architecture):
    infos, reports = [], []
    for name, data in archive_members(Path(path).read_bytes()):
        if name.endswith(('.dll', '.pyd')) and data.startswith(b'MZ'):
            raise RuntimeError(f'{name}: Windows binary in Android package')
        info = elf_info(data, name)
        if info:
            reports.append(validate_elf(info, architecture))
            infos.append(info)
    if not infos:
        raise RuntimeError('Android package contains no ELF binaries')
    available = ANDROID_SYSTEM_LIBRARIES | {Path(p['path'].rsplit(' :: ', 1)[-1]).name for p in infos}
    available |= {p['soname'] for p in infos if p['soname']}
    for info in infos:
        missing = sorted(set(info['needed']) - available)
        if missing:
            raise RuntimeError(f'{info["path"]}: unavailable Android dependencies: {missing}')
    return {'elf_files_checked': len(reports), 'all_nested_elf_architectures_verified': True,
            'android_dependency_closure_verified': True, 'elf_load_and_relro_16kb_verified': True,
            'elf_files': reports}
