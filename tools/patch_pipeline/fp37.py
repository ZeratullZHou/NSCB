import marshal, zlib, sys, io, struct

def code_fingerprint(co, acc):
    acc.append(co.co_code)
    acc.append(repr(co.co_consts.__len__()))
    for c in co.co_consts:
        if hasattr(c, 'co_code'):
            code_fingerprint(c, acc)
        else:
            acc.append(repr(c))
    acc.append(co.co_names)
    return acc

def norm(fn):
    return fn.replace('\\', '/').lower()

pyz = r'D:\switch\nscb_fix_test\extract\squirrel.exe_extracted\PYZ-00.pyz'
raw = io.open(pyz, 'rb').read()
tocpos = struct.unpack('!I', raw[8:12])[0]
toc = marshal.loads(raw[tocpos:])
d = dict((n, t) for n, t in toc)
typ, pos, length = d['Keys']
blob = zlib.decompress(raw[pos:pos+length])
orig_co = marshal.loads(blob)
print('original co_filename:', orig_co.co_filename)

# 1.01b 原版 Keys.py 需从上游 git 历史提取:
#   git show 0cbb7b2:py/ztools/lib/Keys.py
fn = sys.argv[1] if len(sys.argv) > 1 else 'tools/py/ztools/lib/Keys.py'
src = io.open(fn, encoding='utf-8').read()
new_co = compile(src, orig_co.co_filename, 'exec')

a = code_fingerprint(orig_co, [])
b = code_fingerprint(new_co, [])
same = (len(a) == len(b)) and all(x == y for x, y in zip(a, b))
print('FINGERPRINT MATCH:', same)
if not same:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            print('first diff at block', i)
            print('  orig:', str(x)[:200])
            print('  new :', str(y)[:200])
            break
