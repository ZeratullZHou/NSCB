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
import subprocess
from binascii import unhexlify

import Print


# Sanitization for output filenames
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_KEY_LINE = re.compile(r'\s*([a-zA-Z0-9_]+)\s*=\s*([a-fA-F0-9]+)\s*')


def error(msg):
	Print.error('Exception: ' + str(msg))


def _hbp_safe(content):
	'''Heuristic: hacbrewpack rejects known 16-byte keys whose hex value is
	not exactly 32 digits. Return False if such a line exists.'''
	for line in content.splitlines():
		r = re.match(r'\s*([a-zA-Z0-9_]+)\s*=\s*([a-fA-F0-9]+)\s*$', line)
		if not r:
			continue
		name, value = r.group(1), r.group(2)
		if len(value) == 32 or ('rsa' in name or 'keypair' in name or 'certificate' in name):
			continue
		if len(value) not in (64, 128, 256, 512):
			return False
	return True


def _find_keyset(explicit):
	'''Locate a Lockpick-style keyset file (external files only).
	Valid candidates must contain the keys NCA handling needs. When several
	candidates qualify, prefer ones free of malformed entries (some dumps
	carry corrupted lines that hacbrewpack's strict parser rejects).'''
	candidates = []
	if explicit:
		candidates.append(explicit)
	home = os.path.expanduser('~')
	script_dir = os.path.dirname(os.path.abspath(__file__))
	here = os.getcwd()
	for base in (here, script_dir, os.path.join(home, '.switch'), home):
		for name in ('prod.keys', 'keys.txt'):
			candidates.append(os.path.join(base, name))
	first_valid = None
	for path in candidates:
		if not path or not os.path.isfile(path):
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


def _classify_extracted(nca_dir):
	'''Identify exefs/romfs/logo/control/legal among the extracted folders.

	Returns a dict of role -> path. Roles: exefs, romfs, logo, control, legal.
	'''
	roles = {}
	for folder in sorted(glob.glob(os.path.join(nca_dir, '*_nca'))):
		sections = _sections_of(folder)
		for sec in sections:
			files = set(os.listdir(sec))
			if 'main.npdm' in files:
				roles['exefs'] = sec
				for other in sections:
					if other != sec and 'romfs' in os.path.basename(other).lower():
						roles['romfs'] = other
				# a further pfs0 section is only the logo partition when it
				# actually contains the boot logo asset
				for other in sections:
					if other != sec and _is_pfs0(other):
						lfiles = {f.lower() for f in os.listdir(other)}
						if 'nintendologo.png' in lfiles:
							roles['logo'] = other
			elif 'control.nacp' in files:
				roles['control'] = sec
			elif 'legalinfo.xml' in files:
				roles['legal'] = sec
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
	'''Best-effort title name from control.nacp'''
	try:
		from Fs import Nacp
		nc = Nacp(nacp_path)
		for lang in nc.languages:
			if lang.name:
				return lang.name
	except BaseException:
		pass
	return None


def _safe_name(name):
	return _BAD_CHARS.sub('', name).strip().rstrip('.')


def run(args):
	if not args.bake_mod:
		return
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

	outdir = args.ofolder[0] if args.ofolder else os.path.join(os.path.dirname(os.path.abspath(game)), 'MODBAKE_output')
	outdir = os.path.abspath(outdir)
	os.makedirs(outdir, exist_ok=True)
	work = os.path.join(outdir, '_bake_temp')
	if os.path.isdir(work):
		shutil.rmtree(work, ignore_errors=True)
	os.makedirs(work)

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
		roles = _classify_extracted(nca_dir)
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
		hbp_log = os.path.join(work, 'hacbrewpack.log')
		cmd = [hbp, '-k', keyset,
			   '--exefsdir', exefs_dir,
			   '--romfsdir', romfs_dir,
			   '--controldir', control_dir,
			   '--titleid', titleid,
			   '--keygeneration', str(keygen),
			   '--ncadir', os.path.join(work, 'nca_build'),
			   '--tempdir', os.path.join(work, 'hbp_temp'),
			   '--nspdir', outdir]
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
			Print.error('MODBAKE: hacbrewpack failed (exit %d), log: %s' % (ret, hbp_log))
			sys.exit(1)

		built = sorted(glob.glob(os.path.join(outdir, '%s*.nsp' % titleid)), key=os.path.getmtime)
		if not built:
			Print.error('MODBAKE: hacbrewpack reported success but no NSP found in %s' % outdir)
			sys.exit(1)
		src_nsp = built[-1]
		name = _safe_name(tname) if tname else None
		final = os.path.join(outdir, '%s [%s] (MOD).nsp' % (name, titleid)) if name \
			else os.path.join(outdir, '%s (MOD).nsp' % titleid)
		if os.path.abspath(src_nsp) != os.path.abspath(final):
			if os.path.exists(final):
				os.remove(final)
			os.rename(src_nsp, final)

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
	except BaseException as e:
		error(e)
		if args.keep_temp and os.path.isdir(work):
			print('MODBAKE: temp kept for diagnosis at %s' % work)
		sys.exit(1)
	finally:
		if not args.keep_temp and os.path.isdir(work):
			shutil.rmtree(work, ignore_errors=True)
