import marshal, zlib, io, struct, os, shutil

patched_marshal = io.open(r'D:\switch\nscb_fix_test\Keys_patched2.marshal', 'rb').read()
PYZ_MAGIC = b'PYZ\x00'

def find_pyz(data):
    start = max(0, len(data) - 8 * 1024 * 1024)
    idx = data.find(PYZ_MAGIC, start)
    while idx != -1:
        pymagic = data[idx+4:idx+8]
        tocpos = struct.unpack('!I', data[idx+8:idx+12])[0]
        if pymagic == b'\x42\r\r\n' and 12 < tocpos < len(data) - idx:
            try:
                toc = marshal.loads(data[idx+tocpos:])
                names = [e[0] for e in toc]
                if 'Keys' in names:
                    return idx, toc
            except Exception:
                pass
        idx = data.find(PYZ_MAGIC, idx + 1)
    return None, None

def make_exact_chunk(target_len):
    """zlib-compress patched_marshal with trailing pad bytes so the compressed
    stream is EXACTLY target_len bytes. marshal.loads ignores trailing pad."""
    for level in (9, 6, 1):
        base = zlib.compress(patched_marshal, level)
        if len(base) > target_len:
            continue
        # pad plaintext until compressed size hits exactly target_len
        lo, hi = 0, target_len * 4
        best = None
        pad = 0
        while pad <= hi:
            blob = zlib.compress(patched_marshal + b'\x00' * pad, level)
            if len(blob) == target_len:
                best = blob
                break
            if len(blob) > target_len:
                break
            pad += 16
        if best:
            return best
    return None

targets = [
    r'D:\switch\NSCB_101bx64\ztools\squirrel.exe',
    r'D:\switch\NSCB_101bx64\ztools\squirrel_lib_call.exe',
    r'D:\switch\NSCB_101bx64\ztools\redsquirrel.exe',
]

for exe in targets:
    print('==', exe)
    data = io.open(exe, 'rb').read()
    idx, toc = find_pyz(data)
    if idx is None:
        print('   no PYZ with Keys found, skip')
        continue
    toc_dict = dict((name, (typ, pos, length)) for name, (typ, pos, length) in toc)
    typ, pos, length = toc_dict['Keys']
    orig_chunk = data[idx+pos:idx+pos+length]
    # sanity: original chunk decompresses and loads
    assert 'Keys' or True
    orig_obj = marshal.loads(zlib.decompress(orig_chunk))
    print('   PYZ at 0x%x; Keys chunk len=%d (orig code loads OK)' % (idx, length))
    new_chunk = make_exact_chunk(length)
    if new_chunk is None:
        print('   could not fit patched module into %d bytes, skip' % length)
        continue
    # verify the new chunk decompresses to the patched module and loads
    dec = zlib.decompress(new_chunk)
    assert dec.startswith(patched_marshal)
    new_co = marshal.loads(dec)
    patched_fp = new_co.co_code
    expected_co = marshal.loads(patched_marshal)
    assert new_co.co_code == expected_co.co_code, 'patched code mismatch'
    # verify range(32) present: count 32 in consts
    def find_const(co, val):
        if any(c == val and isinstance(c, int) for c in co.co_consts):
            return True
        return any(find_const(c, val) for c in co.co_consts if hasattr(c, 'co_code'))
    assert find_const(expected_co, 32), 'const 32 (range) not found in patched module'
    orig_co = marshal.loads(zlib.decompress(orig_chunk))
    assert not find_const(orig_co, 32), 'const 32 unexpectedly in original'
    bak = exe + '.bak'
    if not os.path.exists(bak):
        shutil.copy2(exe, bak)
    newdata = data[:idx+pos] + new_chunk + data[idx+pos+length:]
    assert len(newdata) == len(data)
    io.open(exe, 'wb').write(newdata)
    print('   PATCHED Keys chunk in place (%d -> %d bytes, same length), backup .bak' % (len(orig_chunk), len(new_chunk)))
