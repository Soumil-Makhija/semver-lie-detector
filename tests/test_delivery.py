import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from semver_lie_detector.cli import main, markdown
from semver_lie_detector.pypi import acquire, extract_sources, require_consecutive, fetch
from semver_lie_detector.surface import scan


def tar_bytes(name='pkg-1/demo/__init__.py', data=b'def f(x): pass\n', link=False):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as t:
        m = tarfile.TarInfo(name)
        if link:
            m.type = tarfile.SYMTYPE; m.linkname = '/tmp/elsewhere'
            t.addfile(m)
        else:
            m.size = len(data); t.addfile(m, io.BytesIO(data))
    return out.getvalue()


class DeliveryTests(unittest.TestCase):
    def test_archive_tar_and_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = extract_sources(tar_bytes(), 'demo.tar.gz', Path(tmp)/'a')
            self.assertIn('demo.f', scan(root / 'demo').symbols)
            out = io.BytesIO()
            with zipfile.ZipFile(out, 'w') as z:
                z.writestr('pkg/src/demo.py', 'raise RuntimeError("must never execute")\ndef f(): pass')
                z.writestr('pkg/README.txt', 'ignored')
            root = extract_sources(out.getvalue(), 'demo.zip', Path(tmp)/'b')
            self.assertIn('demo.f', scan(root / 'src' / 'demo.py').symbols)
            self.assertFalse((root/'README.txt').exists())

    def test_archive_rejects_paths_links_duplicates_and_limits(self):
        for name, link in [('../outside.py', False), ('/absolute.py', False), ('C:/file.py', False), ('pkg/a.py',True), ('pkg\\evil.py',False)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    extract_sources(tar_bytes(name,link=link), 'p.tar.gz', Path(tmp)/'out')
        with tempfile.TemporaryDirectory() as tmp, patch('semver_lie_detector.pypi.MAX_SOURCE', 2):
            with self.assertRaises(ValueError): extract_sources(tar_bytes(), 'p.tar.gz',tmp)
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            z.writestr('demo.py','X=1')
            with self.assertWarns(UserWarning): z.writestr('demo.py','X=2')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): extract_sources(out.getvalue(),'p.zip',tmp)

    def test_acquire_checks_digest_and_module(self):
        data=tar_bytes()
        meta={'urls':[{'packagetype':'sdist','filename':'pkg.tar.gz', 'url':'https://files.pythonhosted.org/pkg.tar.gz', 'digests':{'sha256':hashlib.sha256(data).hexdigest()}, 'yanked':False}]}
        with tempfile.TemporaryDirectory() as tmp, patch('semver_lie_detector.pypi.metadata',return_value=meta), patch('semver_lie_detector.pypi.fetch',return_value=data):
            root, provenance = acquire('demo','1.0.0','demo',Path(tmp)/'a')
            self.assertEqual(provenance['sha256'],hashlib.sha256(data).hexdigest())
            self.assertIn('demo.f',scan(root).symbols)
            meta['urls'][0]['digests']['sha256']='bad'
            with self.assertRaisesRegex(ValueError,'SHA256'): acquire('demo','1.0.0','demo',Path(tmp)/'b')

    def test_consecutive_and_host_policy(self):
        project={'releases':{'1.0.0':[{}], '1.1.0':[{'yanked':True}], '1.2.0':[{}], '2.0.0rc1':[{}], '9.0.0':[]}}
        require_consecutive(project,'1.0.0','1.1.0')
        with self.assertRaises(ValueError): require_consecutive(project,'1.0.0','1.2.0')
        for url in ['http://pypi.org/x','https://evil.test/x','file:///etc/passwd']:
            with self.assertRaises(ValueError): fetch(url)

    def test_cli_json_markdown_determinism_and_exit(self):
        root=Path(__file__).resolve().parents[1]
        args=['local',str(root/'examples/before'),str(root/'examples/after'),'--before-version','1.0.0','--after-version','1.1.0']
        outputs=[]
        for _ in range(2):
            output=io.StringIO()
            with contextlib.redirect_stdout(output): self.assertEqual(main(args),1)
            outputs.append(output.getvalue())
        self.assertEqual(*outputs)
        report=json.loads(outputs[0])
        self.assertEqual(report['summary']['breaking'],3)
        self.assertIn('call-rejected',markdown(report))
        result=subprocess.run([sys.executable,'-m','semver_lie_detector',*args],capture_output=True,text=True,cwd=root)
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads(result.stdout),report)
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'report.md'
            self.assertEqual(main(args+['--format','markdown','--output',str(dest)]),1)
            self.assertIn('Static API',dest.read_text())

    def test_cli_errors_and_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'demo.py'; p.write_text('from missing import x')
            args=['local',str(p),str(p),'--before-version','1.0.0','--after-version','1.0.1']
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args),0)
                self.assertEqual(main(args+['--fail-on-partial']),3)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args+['--after-version','invalid']),2)
                p.write_text('def bad(')
                self.assertEqual(main(args),2)

    def test_pypi_cli_offline_integration(self):
        root=Path(__file__).resolve().parents[1]/'examples'
        project={'releases':{'1.0.0':[{}],'1.1.0':[{}]}}
        with patch('semver_lie_detector.cli.metadata',return_value=project), patch('semver_lie_detector.cli.acquire',side_effect=[(root/'before',{'filename':'a','sha256':'a','yanked':False}),(root/'after',{'filename':'b','sha256':'b','yanked':False})]):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                result=main(['pypi','demo','--module','demo','--before-version','1.0.0','--after-version','1.1.0'])
            self.assertEqual(result,1)
            report=json.loads(output.getvalue())
            self.assertTrue(report['comparison']['consecutive_verified'])
            self.assertEqual(len(report['provenance']),2)

    def test_explicit_private_export_and_no_import_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'demo.py'
            p.write_text('raise RuntimeError("never run")\n__all__=["_f"]\ndef _f(): pass')
            self.assertIn('demo._f',scan(p).symbols)


if __name__ == '__main__': unittest.main()
