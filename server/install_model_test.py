"""Installer data-integrity checks without internet or model imports."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import install_model


class ModelInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent / '_check')
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.pt'
        self.source.write_bytes(b'checked model bytes')
        self.entry = {'url': self.source.as_uri(), 'sha256': hashlib.sha256(self.source.read_bytes()).hexdigest(),
                      'license': 'MIT', 'size_mb': 1}

    def tearDown(self):
        self.tmp.cleanup()

    def test_atomic_verified_download(self):
        install_model.download_verified(self.root, self.entry)
        target = self.root / 'models/source.pt'
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        self.assertFalse(target.with_suffix('.pt.part').exists())
        with patch.object(install_model.urllib.request, 'urlretrieve', side_effect=AssertionError('unnecessary download')):
            install_model.download_verified(self.root, self.entry)

    def test_bad_hash_does_not_promote_download(self):
        self.entry['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            install_model.download_verified(self.root, self.entry)
        self.assertFalse((self.root / 'models/source.pt').exists())
        self.assertFalse((self.root / 'models/source.pt.part').exists())

    def test_interrupted_download_can_be_retried(self):
        (self.root / 'models').mkdir()
        (self.root / 'models/source.pt.part').write_bytes(b'partial')
        install_model.download_verified(self.root, self.entry)
        self.assertEqual((self.root / 'models/source.pt').read_bytes(), self.source.read_bytes())

    def test_update_preserves_config_and_dictionary_bytes(self):
        (self.root / 'models.json').write_text(json.dumps({'silero_v5_ru': self.entry}), encoding='utf-8')
        original = b'{ "token": "keep me", "model": "silero_v5_ru", "port": 8759 }\n'
        (self.root / 'config.json').write_bytes(original)
        (self.root / 'user_dict.json').write_bytes(b'{"word":"accent"}\n')
        with patch.object(install_model, 'ROOT', self.root), patch('sys.argv', ['test', '--unattended']):
            install_model.main()
        self.assertEqual((self.root / 'config.json').read_bytes(), original)
        self.assertEqual((self.root / 'user_dict.json').read_bytes(), b'{"word":"accent"}\n')

    def test_failed_port_save_does_not_destroy_token(self):
        from . import main
        config = self.root / 'config.json'
        original = b'{"token":"keep me","port":8756}'
        config.write_bytes(original)
        with patch.object(main, 'CONFIG_PATH', config), patch.object(Path, 'replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                main.save_config({'token': 'keep me', 'port': 8757})
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual(list(self.root.glob('config.json.*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
