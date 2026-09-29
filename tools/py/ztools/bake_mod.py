# -*- coding: utf-8 -*-
'''
MODBAKE module for NSC_Builder 2.0a

Integrates a LayeredFS mod folder (ExeFs / RomFs layout) into a base game
dump (XCI or NSP) and rebuilds an installable NSP.

Pipeline:
  1. Extract NCAs (with decrypted sections) from the container   (Fs.Xci/Nsp)
  2. Identify program / control / legal content                  (folder scan)
  3. Overlay the mod files                                       (native)
  4. Rebuild the NSP                                             (hacbrewpack)

hacBrewPack by The-4n (bundled as ztools/hacbrewpack.exe, see
hacbrewpack_LICENSE). Key material is only ever loaded from external
keyset files (keys.txt / prod.keys); nothing is embedded.

Rebuilt NCAs carry no Nintendo signature: installing requires sigpatches
(Atmosphere) or DBI / Tinfoil / SX OS.
'''

import os
import re
import sys
import glob
import shutil
import tempfile
import traceback
import subprocess
from binascii import unhexlify

import Print


# Sanitization for output filenames
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_KEY_LINE = re.compile(r'\s*([a-zA-Z0-9_]+)\s*=\s*([a-fA-F0-9]+)\s*')


def error(msg):
	Print.error('Exception: ' + str(msg))


def _hbp_safe_line(line):
	'''True when a keyset line is acceptable to hacbrewpack's strict parser
	(known 16-byte keys must be exactly 32 hex digits).'''
	r = re.match(r'\s*([a-zA-Z0-9_]+)\s*=\s*([a-fA-F0-9]+)\s*$', line)
	if not r:
		return True
	name, value = r.group(1), r.group(2)
	if len(value) == 32 or ('rsa' in name or 'keypair' in name or 'certificate' in name):
		return True
	return len(value) in (64, 128, 256, 512)


def _hbp_safe(content):
	'''Heuristic: hacbrewpack rejects keyset files containing malformed
	entries. Return False if such a line exists.'''
	for line in content.splitlines():
		if not _hbp_safe_line(line):
			return False
	return True


def _hbp_sanitize(keyset_path, dest_path):
	'''Write a copy of the keyset with malformed lines removed, for
	hacbrewpack's strict parser. The copy lives in a temp folder only;
	the original external keyset is never modified.'''
	with open(keyset_path, 'r', encoding='utf-8', errors='ignore') as src, \
		 open(dest_path, 'w', encoding='utf-8', errors='ignore') as dst:
		for line in src:
			if _hbp_safe_line(line.rstrip('\r\n')):
				dst.write(line)


def _ascii_stage_dir(work):
	'''Directory with a pure-ASCII path for files handed to hacbrewpack:
	its keyset loader converts the -k path to UTF-16 assuming UTF-8, so a
	system-codepage (e.g. GBK) path aborts with "Failed to convert ...
	to UTF-16".'''
	for cand in (tempfile.gettempdir(), os.path.dirname(os.path.abspath(__file__))):
		if cand and os.path.join(cand, 'x').isascii():
			return cand
	return work


def _stage_hbp_keyset(keyset, work):
	'''Copy the keyset to an ASCII-safe path for hacbrewpack, dropping
	malformed entries for its strict parser along the way. Returns the
	copy path; the original external keyset stays untouched.'''
	dest = os.path.join(_ascii_stage_dir(work), '_hbp_keys_%d.txt' % os.getpid())
	with open(keyset, 'r', encoding='utf-8', errors='ignore') as f:
		content = f.read()
	if _hbp_safe(content):
		shutil.copyfile(keyset, dest)
	else:
		_hbp_sanitize(keyset, dest)
		print('  -> 密钥文件含损坏行，已生成净化副本供 hacbrewpack 使用')
	return dest


def _find_keyset(explicit):
	'''Locate a Lockpick-style keyset file (external files only).
	Valid candidates must contain the keys NCA handling needs. When several
	candidates qualify, prefer ones free of malformed entries (some dumps
	carry corrupted lines that hacbrewpack's strict parser rejects).
	Searches the script folder, its ancestors (covers repo layouts like
	<repo>/ztools/keys.txt) and the standard ~/.switch location.'''
	candidates = []
	if explicit:
		candidates.append(explicit)
	home = os.path.expanduser('~')
	script_dir = os.path.dirname(os.path.abspath(__file__))
	bases = []
	folder = script_dir
	for _ in range(4):
		bases.append(folder)
		folder = os.path.dirname(folder)
	bases += [os.path.join(home, '.switch'), home]
	for base in bases:
		for rel in ('prod.keys', 'keys.txt', os.path.join('ztools', 'prod.keys'), os.path.join('ztools', 'keys.txt')):
			candidates.append(os.path.join(base, rel))
	seen = set()
	ordered = []
	for path in candidates:
		if not path:
			continue
		key = os.path.normcase(os.path.abspath(path))
		if key not in seen:
			seen.add(key)
			ordered.append(path)
	first_valid = None
	for path in ordered:
		if not os.path.isfile(path):
			continue
		try:
			with open(path, 'r', encoding='utf-8', errors='ignore') as f:
				content = f.read()
		except IOError:
			continue
		if 'header_key' not in content or 'key_area_key_application_' not in content:
			continue
		if first_valid is None:
			first_valid = path
		if _hbp_safe(content):
			return path
	return first_valid


def _prime_pynca3_keys(keyset_path):
	'''
	pyNCA3 snapshots its keyset at import time, which happens during
	squirrel startup - possibly before any keyset was known. Re-fill the
	existing key dict from the resolved external keyset so header parsing
	works. Key material stays in external files / process memory only.
	'''
	from Fs import pyNCA3
	if pyNCA3.keys.get('nca_header_key'):
		return
	parsed = {}
	with open(keyset_path, 'r', encoding='utf-8', errors='ignore') as f:
		for line in f:
			r = _KEY_LINE.search(line)
			if r and r.group(1):
				parsed[r.group(1)] = unhexlify(r.group(2))
	if 'header_key' in parsed:
		parsed['nca_header_key'] = parsed.pop('header_key')
	pyNCA3.keys.clear()
	pyNCA3.keys.update(parsed)
	pyNCA3.NCA3.kaeks = {
		0: pyNCA3.keys.get('key_area_key_application_source'),
		1: pyNCA3.keys.get('key_area_key_ocean_source'),
		2: pyNCA3.keys.get('key_area_key_system_source'),
	}


def _extract_container_ncas(game, dest):
	'''Extract every NCA of the container (with decrypted section contents)
	into dest. Fs.Xci / Fs.Nsp extract_nca() produces one folder per NCA,
	named <contentid>_nca, with '<n> [pfs0]' / '<n> [romfs]' subfolders.
	Returns the container offset list.
	'''
	import sq_tools
	import Fs
	buffer = 65536
	if game.lower().endswith('.xci'):
		files_list = sq_tools.ret_xci_offsets(game)
		f = Fs.Xci(game)
	elif game.lower().endswith('.nsp'):
		files_list = sq_tools.ret_nsp_offsets(game)
		f = Fs.Nsp(game, 'rb')
	else:
		raise ValueError('Unsupported input: %s (use .xci or .nsp)' % os.path.basename(game))
	f.extract_nca(dest, files_list, buffer)
	f.flush()
	f.close()
	return files_list


def _sections_of(nca_folder):
	'''Return the section subfolders of an extracted NCA folder'''
	sections = []
	for sub in sorted(os.listdir(nca_folder)):
		full = os.path.join(nca_folder, sub)
		if os.path.isdir(full):
			sections.append(full)
	return sections


def _is_pfs0(path_):
	return os.path.basename(path_).lower().endswith('pfs0')


def _nca_head_info(nca_folder, game, files_list, nca_dir):
	'''TitleID + keygeneration of an extracted NCA, decrypted from a raw
	4KB head copy. NCA3() is deliberately not used here: its constructor
	also probes section data, which a truncated head copy cannot satisfy
	(and a full standalone copy of every candidate would cost GBs).'''
	import io
	from Fs import pyNCA3
	name = os.path.basename(nca_folder)[:-4] + '.nca'
	entry = None
	for e in files_list:
		if e[0] == name:
			entry = e
			break
	if entry is None:
		raise ValueError('NCA %s not found in container' % name)
	offset, size = entry[1], entry[3]
	with open(game, 'rb') as src:
		src.seek(offset)
		raw_head = src.read(min(0x1000, size))
	header_keys = pyNCA3.keys['nca_header_key'][:0x10], pyNCA3.keys['nca_header_key'][0x10:]
	cipher = pyNCA3.AESXTSN(header_keys)
	raw_header = cipher.decrypt(raw_head)
	header = pyNCA3.NCAHeader(io.BytesIO(raw_header))
	return '%016x' % header.tid, (header.crypto_type_2 or header.crypto_type)


def _classify_extracted(nca_dir, game, files_list):
	'''Identify exefs/romfs/logo/control/legal among the extracted folders.

	Merged containers (base+update+DLC in one file) carry several program
	and control NCAs; the rebuild must use the BASE game content, so among
	the ExeFS candidates the one with the lowest keygeneration wins (update
	NCAs are encrypted for a newer master key). Control / legal / logo
	follow the chosen program's TitleID when one matches.

	Returns a dict of role -> path. Roles: exefs, romfs, logo, control, legal.
	'''
	programs = []   # (keygen, tid, exefs_sec, romfs_sec, logo_sec)
	controls = []   # (tid, control_sec)
	legals = []     # (tid, legal_sec)
	for folder in sorted(glob.glob(os.path.join(nca_dir, '*_nca'))):
		sections = _sections_of(folder)
		files_by_sec = [(sec, set(os.listdir(sec))) for sec in sections]
		exefs_sec = romfs_sec = logo_sec = None
		for sec, files in files_by_sec:
			if 'main.npdm' in files:
				exefs_sec = sec
				for other in sections:
					if other == sec:
						continue
					if 'romfs' in os.path.basename(other).lower():
						romfs_sec = other
					elif _is_pfs0(other) and 'nintendologo.png' in \
							{f.lower() for f in os.listdir(other)}:
						logo_sec = other
				break
		if exefs_sec is not None:
			tid, keygen = _nca_head_info(folder, game, files_list, nca_dir)
			programs.append((keygen, tid, exefs_sec, romfs_sec, logo_sec))
			continue
		for sec, files in files_by_sec:
			if 'control.nacp' in files:
				controls.append((_nca_head_info(folder, game, files_list, nca_dir), sec))
				break
			if 'legalinfo.xml' in files:
				legals.append((_nca_head_info(folder, game, files_list, nca_dir), sec))
				break

	if not programs:
		return {}
	programs.sort(key=lambda p: (p[0], p[1]))
	keygen, tid, exefs_sec, romfs_sec, logo_sec = programs[0]
	if len(programs) > 1:
		print('  -> 检测到 %d 个程序内容（合并包），选择本体: TID %s (keygeneration %d)'
			  % (len(programs), tid, keygen))
	roles = {'exefs': exefs_sec}
	if romfs_sec:
		roles['romfs'] = romfs_sec
	if logo_sec:
		roles['logo'] = logo_sec

	def _pick(cands):
		for c_tid, sec in cands:
			if c_tid == tid:
				return sec
		return cands[0][1] if cands else None

	control = _pick(controls)
	if control:
		roles['control'] = control
	legal = _pick(legals)
	if legal:
		roles['legal'] = legal
	return roles


def _ensure_standalone_nca(game, files_list, nca_dir, prog_folder):
	'''Make sure the program NCA also exists as a standalone file.

	pyNCA3 parses headers reliably from a standalone file (offset 0), while
	parsing at a container offset is unreliable. Xci/Nsp extract_nca already
	writes a standalone copy for NCAs that hit its fallback path; for the
	rest we do a raw sequential copy (no decryption) ourselves.
	'''
	prog_name = os.path.basename(prog_folder)[:-4] + '.nca'
	standalone = os.path.join(nca_dir, prog_name)
	if os.path.isfile(standalone):
		return standalone
	entry = None
	for e in files_list:
		if e[0] == prog_name:
			entry = e
			break
	if entry is None:
		raise ValueError('program NCA %s not found in container' % prog_name)
	offset, size = entry[1], entry[3]
	with open(game, 'rb') as src, open(standalone, 'w+b') as dst:
		src.seek(offset)
		remaining = size
		while remaining > 0:
			chunk = src.read(min(1024 * 1024, remaining))
			if not chunk:
				break
			dst.write(chunk)
			remaining -= len(chunk)
	return standalone


def _read_program_header(game, files_list, nca_dir, exefs_dir):
	'''Read the program NCA header (tid / keygeneration / sdk / rightsId)
	from the standalone program NCA file.'''
	from Fs.pyNCA3 import NCA3
	prog_folder = os.path.dirname(exefs_dir)
	standalone = _ensure_standalone_nca(game, files_list, nca_dir, prog_folder)
	with open(standalone, 'rb') as fh:
		header = NCA3(fh).header
		crypto1 = header.crypto_type
		crypto2 = header.crypto_type_2
		sdkver = None
		try:
			# pyNCA3 stores sdk_rev as the char-reversed join of the raw
			# bytes at 0x21C..0x21F; byte order there is rev, micro, minor,
			# major. hacBrewPack wants e.g. 14.3.0.0 as '000E0300'.
			p = [int(x[::-1]) for x in header.sdk_rev.split('.')][::-1]
			major, minor, micro = p[3], p[2], p[1]
			sdkver = '%04X%02X%02X' % (major, minor, micro)
		except (ValueError, IndexError):
			pass
		return {
			'titleid': '%016x' % header.tid,
			'keygen': crypto2 if crypto2 else crypto1,
			'sdk': sdkver,
			'rights': header.rights_id,
		}


def _overlay(src, dst):
	'''Recursively copy src over dst without clearing dst (py3.7-safe)'''
	for dirpath, dirnames, filenames in os.walk(src):
		rel = os.path.relpath(dirpath, src)
		target = dst if rel == '.' else os.path.join(dst, rel)
		os.makedirs(target, exist_ok=True)
		for name in filenames:
			shutil.copy2(os.path.join(dirpath, name), os.path.join(target, name))


def _title_name(nacp_path):
	'''Best-effort title name from control.nacp: the first non-empty
	display name across languages. Nacp must be opened with an explicit
	mode (BaseFile skips opening otherwise) and only parses an entry
	when getName(i) is called; both were missing before, so the name
	silently resolved to None for every game.'''
	try:
		from Fs import Nacp
		nc = Nacp(nacp_path, 'rb')
		try:
			for i in range(len(nc.languages)):
				name = nc.getName(i)
				if name:
					return name
		finally:
			nc.close()
	except BaseException:
		pass
	return None


def _safe_name(name):
	return _BAD_CHARS.sub('', name).strip().rstrip('.')


def _find_prog_root():
	'''Locate the program root whose NSCB.bat actually drives this script:
	the highest ancestor that holds the bat alongside this script's own
	folder (as tools/py/ztools, ztools_2a or ztools). The repo tree nests
	a complete upstream deployment under tools/py, so "first match wins"
	would stop too early — keep the highest instead.'''
	script_dir = os.path.dirname(os.path.abspath(__file__))
	best = None
	folder = script_dir
	for _ in range(5):
		if os.path.isfile(os.path.join(folder, 'NSCB.bat')):
			for rel in (os.path.join('tools', 'py', 'ztools'), 'ztools_2a', 'ztools'):
				if os.path.normcase(os.path.abspath(os.path.join(folder, rel))) == os.path.normcase(script_dir):
					best = folder
					break
		parent = os.path.dirname(folder)
		if parent == folder:
			break
		folder = parent
	return best


def _sweep_stale_workdirs(root, age_hours=24):
	'''Best-effort cleanup of work dirs left behind by hard-killed runs
	(e.g. a closed console window skips the finally block): only entries
	older than a day are removed, so concurrent bakes are never touched.'''
	import time
	try:
		now = time.time()
		for name in os.listdir(root):
			if not name.startswith('_modbake_'):
				continue
			p = os.path.join(root, name)
			if os.path.isdir(p) and now - os.path.getmtime(p) > age_hours * 3600:
				shutil.rmtree(p, ignore_errors=True)
	except OSError:
		pass


def _make_work_dir(outdir, game):
	'''Temp work dir for every intermediate, anchored at the first
	ASCII-safe location: hacbrewpack converts every path it is handed
	(keyset, exefsdir, romfsdir, ...) to UTF-16 assuming UTF-8, so a
	system-codepage (GBK) work dir kills the rebuild with "Failed to
	convert ... to UTF-16". The conventional system temp folder comes
	first (invisible to the user; stale dirs get OS-cleaned eventually),
	gated by a free-space check, then the output/game volumes for the
	same-volume rename, then ProgramData and the script dir. It never
	lives inside outdir itself, so the output dir only ever receives the
	final file.'''
	cands = []
	t = tempfile.gettempdir()
	if t and os.path.isdir(t) and os.path.join(t, 'x').isascii():
		try:
			game_size = os.path.getsize(game)
		except OSError:
			game_size = 0
		try:
			# extraction + rebuild needs roughly 2.5x the game size
			if shutil.disk_usage(t).free > game_size * 2.5 + (1 << 30):
				cands.append(t)
		except OSError:
			pass
	for d in (os.path.dirname(outdir), os.path.dirname(game),
			  os.path.expandvars('%ProgramData%'),
			  os.path.dirname(os.path.abspath(__file__))):
		if d and os.path.isdir(d) and os.path.join(d, 'x').isascii():
			cands.append(d)
	for root in cands:
		try:
			work = tempfile.mkdtemp(prefix='_modbake_', dir=root)
		except OSError:
			continue
		_sweep_stale_workdirs(root)
		return work
	# nothing ASCII worked; same-volume chain as a last resort (extraction
	# still runs, but hacbrewpack may refuse the non-ASCII paths)
	for root in (os.path.dirname(outdir), os.path.dirname(game), None):
		if root is not None and not os.path.isdir(root):
			continue
		try:
			work = tempfile.mkdtemp(prefix='_modbake_', dir=root)
			Print.warning('MODBAKE: 未找到纯 ASCII 的临时目录，使用 %s（hacbrewpack 可能拒绝中文路径）' % work)
			return work
		except OSError:
			continue
	raise OSError('MODBAKE: could not create a temp work dir')


def run(args):
	if not args.bake_mod:
		return
	# Never let an unencodable path/ name kill the run on a redirected or
	# legacy-codepage console; replace instead.
	try:
		sys.stdout.reconfigure(errors='replace')
		sys.stderr.reconfigure(errors='replace')
	except BaseException:
		pass
	game = args.bake_mod[0]
	if len(args.bake_mod) > 1 and not args.mod_path:
		args.mod_path = [args.bake_mod[1]]
	if not args.mod_path:
		Print.error('MODBAKE: --mod_path <mod folder> is required (folder containing ExeFs / RomFs)')
		sys.exit(1)
	moddir = args.mod_path[0]
	if not os.path.isfile(game):
		Print.error('MODBAKE: input file not found: %s' % game)
		sys.exit(1)
	if not os.path.isdir(moddir):
		Print.error('MODBAKE: mod folder not found: %s' % moddir)
		sys.exit(1)

	# Resolve mod layout (any case: ExeFs/exefs, RomFs/romfs)
	mod_exefs = mod_romfs = None
	for entry in os.listdir(moddir):
		full = os.path.join(moddir, entry)
		if not os.path.isdir(full):
			continue
		if entry.lower() == 'exefs':
			mod_exefs = full
		elif entry.lower() == 'romfs':
			mod_romfs = full
	if mod_romfs is None and mod_exefs is None:
		Print.error('MODBAKE: no ExeFs / RomFs folder inside mod dir: %s' % moddir)
		sys.exit(1)

	keyset = _find_keyset(args.keyset[0] if args.keyset else None)
	if keyset is None:
		Print.error('MODBAKE: no usable keyset found (need keys.txt or prod.keys with header_key); use -k')
		sys.exit(1)

	# squirrel imports Keys at startup, before arguments are known; if its
	# default search (cwd / ztools) found nothing, reload from the resolved
	# external keyset now. Keys are only ever read from external files.
	try:
		import Keys as nscb_keys
		nscb_keys.load(keyset)
	except BaseException as e:
		Print.error('MODBAKE: failed loading keyset into Keys: %s' % e)
		sys.exit(1)

	# pyNCA3 snapshots its keyset at startup import time; re-fill it from
	# the resolved external keyset before any decryption happens.
	_prime_pynca3_keys(keyset)

	hbp = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hacbrewpack.exe')
	if not os.path.isfile(hbp):
		Print.error('MODBAKE: hacbrewpack.exe not found next to squirrel (expected %s)' % hbp)
		sys.exit(1)

	if args.ofolder:
		outdir = args.ofolder[0]
	else:
		# default to the tool's own NSCB_output folder; game-adjacent
		# fallback when the program root can't be located
		root = _find_prog_root()
		outdir = os.path.join(root, 'NSCB_output') if root else \
			os.path.join(os.path.dirname(os.path.abspath(game)), 'MODBAKE_output')
	outdir = os.path.abspath(outdir)
	# All intermediates (extracted NCAs, hacbrewpack build/temp, logs,
	# sanitized keyset, the raw built NSP) stay in the temp work dir;
	# outdir is only created when the finished NSP is moved in, so a
	# failed run leaves no trace in the output location.
	work = _make_work_dir(outdir, game)
	# Persistent diagnostics: the temp work dir (incl. the hacbrewpack
	# log) is wiped on failure, so keep the evidence where the menu's cls
	# cannot reach it and the user can inspect it after the fact.
	diag_log = os.path.join(tempfile.gettempdir(), 'MODBAKE_last_error.log')
	hbp_log = os.path.join(work, 'hacbrewpack.log')
	hbp_keyset = None

	print('**************************************************************************')
	print('                     NSC_Builder 2.0a -- MODBAKE                          ')
	print('**************************************************************************')
	print('  游戏:     %s' % os.path.basename(game))
	print('  Mod:      %s' % os.path.basename(moddir))
	print('  输出:     %s' % outdir)
	print('  密钥:     %s' % os.path.basename(keyset))
	print('')

	try:
		# ---- 1. Container -> NCAs (with decrypted sections) -----------------
		print('[1/4] 解包容器中的 NCA（含解密内容，数分钟）...')
		nca_dir = os.path.join(work, 'nca')
		os.makedirs(nca_dir)
		files_list = _extract_container_ncas(game, nca_dir)

		# ---- 2. Identify content --------------------------------------------
		print('[2/4] 识别 Program / Control / Legal ...')
		_prime_pynca3_keys(keyset)
		roles = _classify_extracted(nca_dir, game, files_list)
		for required in ('exefs', 'romfs', 'control'):
			if required not in roles:
				Print.error('MODBAKE: could not locate %s content in extracted NCA folders' % required)
				sys.exit(1)
		exefs_dir = roles['exefs']
		romfs_dir = roles['romfs']
		control_dir = roles['control']
		legal_dir = roles.get('legal')
		logo_dir = roles.get('logo')

		header = _read_program_header(game, files_list, nca_dir, exefs_dir)
		titleid = header['titleid']
		keygen = header['keygen']
		sdkver = header['sdk']
		if sdkver and int(sdkver, 16) < 0x000B0000:
			# hacbrewpack rejects SDK versions below 11.0.0; the field is
			# informational metadata in the rebuilt NCA, so clamp it.
			print('  -> 原始 SDK 版本过低（%s），重建时改用 000B0000' % sdkver)
			sdkver = '000B0000'
		if header['rights']:
			# Some converted dumps carry a rightsId while their NCAs stay
			# standard-crypto encrypted. Extraction quality is what matters;
			# hacbrewpack + the final NSP hash check will catch real damage.
			print('  -> 注意: NCA 带 rightsId（常见于转换 dump）；若内容解密异常会在构建时报错')
		print('  -> ExeFS:  %s' % exefs_dir)
		print('  -> RomFS:  %s' % romfs_dir)
		print('  -> Control: %s' % os.path.basename(control_dir))
		print('  -> TitleID: %s | keygeneration: %d | SDK: %s' % (titleid, keygen, sdkver))

		# ---- 3. Overlay the mod ---------------------------------------------
		print('[3/4] 覆盖 mod 文件 ...')
		if mod_exefs:
			_overlay(mod_exefs, exefs_dir)
			print('  -> ExeFs 已覆盖: %s' % os.path.basename(mod_exefs))
		if mod_romfs:
			_overlay(mod_romfs, romfs_dir)
			print('  -> RomFs 已覆盖: %s' % os.path.basename(mod_romfs))
		if not os.path.exists(os.path.join(exefs_dir, 'main.npdm')):
			Print.error('MODBAKE: main.npdm missing after overlay')
			sys.exit(1)

		# ---- 4. Rebuild with hacbrewpack ------------------------------------
		print('[4/4] hacbrewpack 重建 NSP（需要数分钟）...')
		tname = _title_name(os.path.join(control_dir, 'control.nacp'))
		# hacbrewpack converts the -k path to UTF-16 assuming UTF-8 (a GBK
		# path kills the rebuild) and its strict parser rejects malformed
		# keyset entries. Always stage a copy at an ASCII-safe location,
		# sanitized when needed; the original stays untouched.
		hbp_keyset = _stage_hbp_keyset(keyset, work)
		build_dir = os.path.join(work, 'build')
		os.makedirs(build_dir)
		cmd = [hbp, '-k', hbp_keyset,
			   '--exefsdir', exefs_dir,
			   '--romfsdir', romfs_dir,
			   '--controldir', control_dir,
			   '--titleid', titleid,
			   '--keygeneration', str(keygen),
			   '--ncadir', os.path.join(work, 'nca_build'),
			   '--tempdir', os.path.join(work, 'hbp_temp'),
			   '--nspdir', build_dir]
		if sdkver:
			cmd += ['--sdkversion', sdkver]
		if legal_dir:
			cmd += ['--legalinfodir', legal_dir]
		if logo_dir:
			cmd += ['--logodir', logo_dir]
		else:
			cmd += ['--nologo']
		with open(hbp_log, 'wb') as lf:
			ret = subprocess.call(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=work)
		if ret != 0:
			with open(hbp_log, 'r', encoding='utf-8', errors='ignore') as f:
				tail = f.read()[-2000:]
			print(tail)
			try:
				with open(diag_log, 'w', encoding='utf-8') as df:
					df.write('game:   %s\nmod:    %s\noutdir: %s\n\n' % (game, moddir, outdir))
					with open(hbp_log, 'r', encoding='utf-8', errors='ignore') as lf:
						df.write(lf.read())
				Print.error('MODBAKE: hacbrewpack failed (exit %d), full log saved to: %s' % (ret, diag_log))
			except OSError:
				Print.error('MODBAKE: hacbrewpack failed (exit %d), log: %s' % (ret, hbp_log))
			sys.exit(1)

		built = sorted(glob.glob(os.path.join(build_dir, '%s*.nsp' % titleid)), key=os.path.getmtime)
		if not built:
			Print.error('MODBAKE: hacbrewpack reported success but no NSP found in %s' % build_dir)
			sys.exit(1)
		src_nsp = built[-1]
		name = _safe_name(tname) if tname else None
		final = os.path.join(outdir, '%s [%s] (MOD).nsp' % (name, titleid)) if name \
			else os.path.join(outdir, '%s (MOD).nsp' % titleid)
		os.makedirs(outdir, exist_ok=True)
		if os.path.exists(final):
			os.remove(final)
		print('  -> 写入成品到输出目录 ...')
		shutil.move(src_nsp, final)

		print('')
		print('**************************************************************************')
		print('  完成! 产物: %s' % final)
		print('  大小: %.2f GB' % (os.path.getsize(final) / (1024 * 1024 * 1024)))
		if tname:
			print('  名称: %s' % tname)
		print('  注意: 重建的 NCA 无任天堂签名，安装需要大气层 sigpatches + DBI/Tinfoil，')
		print('        或 SX OS。请勿在未破解主机上安装，请勿对外分发。')
		print('  校验: 可用 squirrel -v "%s" 做完整性检查' % final)
		print('**************************************************************************')
	except SystemExit:
		# Deliberate exits (hacbrewpack failure, validation) have already
		# printed their own diagnostics; don't re-report them as "Exception: 1".
		raise
	except BaseException as e:
		error(e)
		# The menu cls-wipes the console right after this returns; persist
		# the traceback (and the hacbrewpack log tail) for post-mortem.
		try:
			with open(diag_log, 'w', encoding='utf-8') as df:
				df.write('game:   %s\nmod:    %s\noutdir: %s\n\n' % (game, moddir, outdir))
				traceback.print_exc(file=df)
				if os.path.isfile(hbp_log):
					df.write('\n--- hacbrewpack log tail ---\n')
					with open(hbp_log, 'r', encoding='utf-8', errors='ignore') as lf:
						df.write(lf.read()[-4000:])
			print('MODBAKE: 错误详情已写入 %s' % diag_log)
		except OSError:
			pass
		if args.keep_temp and os.path.isdir(work):
			print('MODBAKE: temp kept for diagnosis at %s' % work)
		sys.exit(1)
	finally:
		try:
			if hbp_keyset and os.path.abspath(hbp_keyset) != os.path.abspath(keyset) \
					and os.path.isfile(hbp_keyset):
				os.remove(hbp_keyset)
		except (OSError, UnboundLocalError):
			pass
		if not args.keep_temp and os.path.isdir(work):
			shutil.rmtree(work, ignore_errors=True)
