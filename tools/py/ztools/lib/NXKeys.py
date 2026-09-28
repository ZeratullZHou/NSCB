import os.path as path
import re
from binascii import hexlify as hx, unhexlify as uhx
from pathlib import Path
my_file = Path('keys.txt')
my_file2 = Path('ztools\\keys.txt')

# Optional explicit keyset path (external file only, never embedded).
# MODBAKE sets this from the -k/--keyset argument before importing pyNCA3.
explicit_keyset = None

class Keys(dict):
	def __init__(self, keys_type):
		self.keys_type = keys_type
		is_key  = re.compile(r'''\s*([a-zA-Z0-9_]*)\s* # name
								=
								\s*([a-fA-F0-9]*)\s* # key''', re.X)
		# All key sources are external files; nothing is hardcoded here.
		candidates = []
		if explicit_keyset:
			candidates.append(explicit_keyset)
		candidates += ['keys.txt', 'ztools\\keys.txt',
				path.join(path.dirname(path.abspath(__file__)), 'keys.txt'),
				path.join(path.expanduser('~'), '.switch', 'keys.txt'),
				path.join(path.expanduser('~'), '.switch', 'prod.keys')]
		f = None
		for candidate in candidates:
			if candidate and path.isfile(candidate):
				f = open(candidate, 'r')
				break
		if f is None:
			# Non-fatal: allow the interpreter to start without keys
			# (modes that actually need keys will fail later with a
			# clear 'Missing key' message). Keys are external files only.
			print('NXKeys: no keyset file found (searched: %s)' % ', '.join(candidates))
			super(Keys, self).__init__()
			return
		iterator = (re.search(is_key, l) for l in f)
		super(Keys, self).__init__({r[1]: uhx(r[2]) for r in iterator if r is not None})
		f.close()

	def __getitem__(self, item):
		try:
			return dict.__getitem__(self, item)
		except KeyError:
			raise KeyError('Missing key %s in %s' % (item, self.keys_type))

class ProdKeys(Keys):
	def __init__(self):
		super(ProdKeys, self).__init__('keys.txt')
		if 'header_key' in self:
			self['nca_header_key'] = self.pop('header_key')

class DevKeys(Keys):
	def __init__(self):
		super(DevKeys, self).__init__('dev')

class TitleKeys(Keys):
	def __init__(self):
		super(TitleKeys, self).__init__('title')
		if 'header_key' in self:
			self['nca_header_key'] = self.pop('header_key')
