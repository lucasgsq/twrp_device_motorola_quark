#!/usr/bin/env python3
"""Add only /misc to the verified official Quark TWRP ramdisk; never access a device."""
import argparse
import gzip
import hashlib
import json
import lzma
import struct
from pathlib import Path

OFFICIAL_SHA256 = '0d0fcb443c8f2dc9ead3f01d2a4f4d8e01df463e16321e3df4de0194027eb755'
MISC_LINE = b'/misc            emmc              /dev/block/platform/msm_sdcc.1/by-name/misc\n'


def align(value, page):
    return (value + page - 1) // page * page


def boot_parts(image):
    if image[:8] != b'ANDROID!':
        raise ValueError('Not a legacy Android boot image')
    page = struct.unpack_from('<I', image, 36)[0]
    if page != 4096:
        raise ValueError('Unexpected page size')
    sizes = [struct.unpack_from('<I', image, offset)[0] for offset in (8, 16, 24, 40)]
    offset = page
    parts = []
    for size in sizes:
        if offset + size > len(image):
            raise ValueError('Truncated image')
        parts.append(image[offset:offset + size])
        offset += align(size, page)
    if offset != len(image):
        raise ValueError('Unrecognized image trailer; refusing to discard it')
    digest = hashlib.sha1()
    for part in parts:
        digest.update(part)
        digest.update(struct.pack('<I', len(part)))
    if image[576:596] != digest.digest():
        raise ValueError('Legacy boot image ID does not match its payloads')
    return page, parts


def cpio_entries(raw):
    offset = 0
    entries = []
    while offset + 110 <= len(raw):
        start = offset
        magic = raw[start:start + 6]
        if magic not in (b'070701', b'070702'):
            raise ValueError('Unsupported cpio header')
        fields = [int(raw[start + 6 + 8 * i:start + 14 + 8 * i], 16) for i in range(13)]
        size, name_size = fields[6], fields[11]
        name_start = start + 110
        if name_size < 1 or name_start + name_size > len(raw):
            raise ValueError('Invalid cpio name')
        name_bytes = raw[name_start:name_start + name_size]
        if not name_bytes.endswith(b'\0'):
            raise ValueError('Unterminated cpio name')
        name = name_bytes[:-1].decode('utf-8')
        data_start = align(name_start + name_size, 4)
        data_end = data_start + size
        end = align(data_end, 4)
        if end > len(raw):
            raise ValueError('Truncated cpio payload')
        entry = {'name': name, 'start': start, 'data_start': data_start,
                 'data_end': data_end, 'end': end, 'fields': fields,
                 'data': raw[data_start:data_end], 'magic': magic}
        entries.append(entry)
        offset = end
        if name == 'TRAILER!!!':
            if any(raw[offset:]):
                raise ValueError('Nonzero data after cpio trailer')
            return entries
    raise ValueError('Missing cpio trailer')


def patch_image(image):
    if hashlib.sha256(image).hexdigest() != OFFICIAL_SHA256:
        raise ValueError('Input is not the verified official twrp-3.7.0_9-0-quark.img')
    page, parts = boot_parts(image)
    if parts[1][:2] == b'\x1f\x8b':
        raw = gzip.decompress(parts[1])
        compression = 'gzip'
    else:
        raw = lzma.decompress(parts[1], format=lzma.FORMAT_ALONE)
        compression = 'lzma-alone'
    entries = cpio_entries(raw)
    targets = [entry for entry in entries if entry['name'] == 'etc/recovery.fstab']
    if len(targets) != 1:
        raise ValueError('Expected exactly one recovery.fstab')
    entry = targets[0]
    fstab = entry['data']
    if any(line.split() and line.split()[0] == b'/misc' for line in fstab.splitlines()):
        raise ValueError('/misc is already declared; refusing to add a duplicate')
    if not fstab.endswith(b'\n'):
        raise ValueError('Unexpected fstab termination')
    replacement = fstab + MISC_LINE
    header = bytearray(raw[entry['start']:entry['data_start']])
    header[54:62] = ('%08x' % len(replacement)).encode()
    if entry['magic'] == b'070702':
        header[102:110] = ('%08x' % (sum(replacement) & 0xffffffff)).encode()
    encoded = bytes(header) + replacement
    encoded += b'\0' * (align(len(encoded), 4) - len(encoded))
    new_raw = raw[:entry['start']] + encoded + raw[entry['end']:]
    new_raw += b'\0' * (align(len(new_raw), 512) - len(new_raw))
    new_entries = cpio_entries(new_raw)
    if [e['name'] for e in new_entries] != [e['name'] for e in entries]:
        raise ValueError('Archive entry list changed unexpectedly')
    changed = []
    for old, new in zip(entries, new_entries):
        if old['data'] != new['data']:
            changed.append(old['name'])
        for field in (0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11):
            if old['fields'][field] != new['fields'][field]:
                raise ValueError('Archive metadata changed unexpectedly')
    if changed != ['etc/recovery.fstab']:
        raise ValueError('Unexpected archive modifications')
    modified = list(parts)
    if compression == 'gzip':
        modified[1] = gzip.compress(new_raw, compresslevel=9, mtime=0)
    else:
        properties = parts[1][0]
        lc = properties % 9
        lp = (properties // 9) % 5
        pb = properties // 45
        dictionary = struct.unpack_from('<I', parts[1], 1)[0]
        modified[1] = lzma.compress(new_raw, format=lzma.FORMAT_ALONE,
                filters=[{'id': lzma.FILTER_LZMA1, 'dict_size': dictionary,
                          'lc': lc, 'lp': lp, 'pb': pb}])
    boot_header = bytearray(image[:page])
    struct.pack_into('<I', boot_header, 16, len(modified[1]))
    digest = hashlib.sha1()
    for part in modified:
        digest.update(part)
        digest.update(struct.pack('<I', len(part)))
    boot_header[576:608] = digest.digest() + b'\0' * 12
    output = bytes(boot_header)
    for part in modified:
        output += part + b'\0' * (align(len(part), page) - len(part))
    if len(output) > 16 * 1024 * 1024:
        raise ValueError('Candidate exceeds the conservative 16 MiB partition limit')
    _, check = boot_parts(output)
    if any(check[i] != parts[i] for i in (0, 2, 3)):
        raise ValueError('Kernel, second stage or device tree changed')
    if check[1] != modified[1]:
        raise ValueError('Ramdisk mismatch')
    return output, {
        'input_sha256': OFFICIAL_SHA256,
        'output_sha256': hashlib.sha256(output).hexdigest(),
        'output_size': len(output),
        'ramdisk_compression_preserved': compression,
        'changed_ramdisk_files': changed,
        'kernel_unchanged': True,
        'device_tree_unchanged': True,
        'boot_header_id_verified': True,
        'tested_on_device': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix('.json').exists():
        parser.error('Output already exists; choose a new name')
    output, report = patch_image(args.input.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(output)
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    print('Experimental image only. No device was accessed or flashed.')


if __name__ == '__main__':
    main()
