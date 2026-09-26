import marshal, zlib, io, struct, sys

ORIG_CO_FILENAME = 'lib\\Keys.py'
pyz_path = r'D:\switch\nscb_fix_test\extract\squirrel.exe_extracted\PYZ-00.pyz'

def compile_to_marshal(src_path, co_filename):
    src = io.open(src_path, encoding='utf-8').read()
    co = compile(src, co_filename, 'exec')
    return marshal.dumps(co)

# original blob from PYZ
raw = io.open(pyz_path, 'rb').read()
tocpos = struct.unpack('!I', raw[8:12])[0]
toc = dict(marshal.loads(raw[tocpos:]))
typ, pos, length = toc['Keys']
orig_blob = zlib.decompress(raw[pos:pos+length])
print('orig blob len:', len(orig_blob))

# compile unmodified 1.01b source, byte-compare
repro = compile_to_marshal(r'D:\switch\nscb_fix_test\Keys_101b.py', ORIG_CO_FILENAME)
print('repro blob len:', len(repro))
print('BYTE-IDENTICAL to original:', repro == orig_blob)

# compile patched source
patched = compile_to_marshal(r'D:\switch\nscb_fix_test\Keys_patched.py', ORIG_CO_FILENAME)
io.open(r'D:\switch\nscb_fix_test\Keys_patched.marshal', 'wb').write(patched)
print('patched blob len:', len(patched), '-> Keys_patched.marshal')
