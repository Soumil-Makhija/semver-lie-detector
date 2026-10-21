from pathlib import Path
import tempfile
import unittest
from semver_lie_detector.surface import scan
from semver_lie_detector.compare import compare, version_policy


class CoreTests(unittest.TestCase):
    def surfaces(self, before, after):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for version, source in [('old', before), ('new', after)]:
            (root / version).mkdir()
            (root / version / 'demo.py').write_text(source)
        return scan(root / 'old'), scan(root / 'new')

    def diff(self, before, after, versions=('1.0.0', '1.1.0')):
        return compare(*self.surfaces(before, after), *versions)

    def test_removed_and_minor_policy(self):
        report = self.diff('def f(): pass\nX=1', 'X=1')
        self.assertTrue(report['suspected_violation'])
        self.assertEqual(report['findings'][0]['rule'], 'removed')

    def test_keyword_only_break_has_actual_witness(self):
        report = self.diff('def f(x, y=1): pass', 'def f(x, *, y=1): pass')
        w = report['findings'][0]['witness']
        self.assertEqual(w['args'], [0, 1])
        old, new = self.surfaces('def f(x, y=1): pass', 'def f(x, *, y=1): pass')
        old.symbols['demo.f'].signature.bind(*w['args'], **w['kwargs'])
        with self.assertRaises(TypeError):
            new.symbols['demo.f'].signature.bind(*w['args'], **w['kwargs'])

    def test_call_domains(self):
        pairs = [
            ('x=1', 'x', True), ('x', 'x, y=1', False),
            ('x', 'x, *, y', True), ('x', 'x, *, y=1', False),
            ('x', 'x, /', True), ('x, /', 'y, /', False),
            ('*args', 'x=1', True), ('**kwargs', '', True),
            ('x, **kw', 'x, y=1, **kw', False),
            ('x=1, **kw', 'x=1, /, **kw', False),
            ('x, *args, **kw', 'x, *args, **kw', False),
            ('x, /, **kw', 'x, **kw', True),
        ]
        for a, b, breaking in pairs:
            with self.subTest(a=a, b=b):
                report = self.diff(f'def f({a}): pass', f'def f({b}): pass')
                self.assertEqual(report['suspected_violation'], breaking)

    def test_posonly_keyword_matches_actual_runtime(self):
        import inspect
        from semver_lie_detector.compare import bind_call
        def target(x=1, /, **kw):
            return x, kw
        self.assertEqual(target(x=2), (1, {'x': 2}))
        self.assertEqual(bind_call(inspect.signature(target), [], {'x': 2}).arguments['kw'], {'x': 2})

    def test_order_default_async_and_review(self):
        self.assertTrue(self.diff('def f(x,y): pass', 'def f(y,x): pass')['suspected_violation'])
        report = self.diff('def f(x=1): pass', 'def f(x=2): pass')
        self.assertFalse(report['suspected_violation'])
        self.assertEqual(report['summary']['review'], 1)
        self.assertTrue(self.diff('def f(): pass', 'async def f(): pass')['suspected_violation'])

    def test_public_all_private_and_reexport(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'demo'; p.mkdir()
            (p / '__init__.py').write_text('__all__=["f", "Alias"]\nfrom ._impl import f, Client as Alias\ndef ignored(): pass\n')
            (p / '_impl.py').write_text('def f(x): pass\nclass Client:\n def send(self,x): pass\n')
            s = scan(p)
            self.assertIn('demo.f', s.symbols)
            self.assertIn('demo.Alias.send', s.symbols)
            self.assertNotIn('demo.ignored', s.symbols)
            self.assertNotIn('demo._impl.f', s.symbols)
            self.assertFalse(s.warnings)

    def test_methods_properties_and_constructor(self):
        a = '''class C:
 def __init__(self,x=1): pass
 @staticmethod
 def f(x): pass
 @classmethod
 def g(cls,y): pass
 @property
 def value(self): return 1
'''
        b = a.replace('x=1', 'x').replace('@staticmethod', '@classmethod')
        r = self.diff(a,b)
        self.assertTrue(r['suspected_violation'])
        self.assertIn('binding-changed', [f['rule'] for f in r['findings']])
        old, _ = self.surfaces(a,b)
        self.assertEqual(str(old.symbols['demo.C.g'].signature), '(y)')

    def test_partial_and_syntax_errors_are_visible(self):
        r = self.diff('from external import f\n', 'from external import f\nif True:\n X=1')
        self.assertEqual(r['analysis'], 'partial')
        self.assertFalse(r['suspected_violation'])
        with self.assertRaises(ValueError):
            self.surfaces('def broken(', 'X=1')

    def test_complex_signature_is_partial(self):
        args = ','.join(f'a{i}=1' for i in range(13))
        r = self.diff(f'def f({args}): pass', f'def f({args}, extra=1): pass')
        self.assertEqual(r['analysis'], 'partial')

    def test_version_policy(self):
        for old, new, enforce in [('1.2.3','1.2.4',True), ('1.2.3','1.3.0',True), ('1.2.3','2.0.0',False), ('0.2.0','0.2.1',False), ('1.0.0+abc','1.0.1',True)]:
            self.assertEqual(version_policy(old,new)[1], enforce)
        for new in ['1.0.0', '0.9.0', '1.1.0rc1', '01.2.3', '1.1']:
            with self.assertRaises(ValueError): version_policy('1.0.0',new)

    def test_example(self):
        root = Path(__file__).resolve().parents[1] / 'examples'
        r = compare(scan(root/'before'), scan(root/'after'), '1.0.0', '1.1.0')
        self.assertTrue(r['suspected_violation'])
        self.assertEqual(r['analysis'], 'static-subset')
        self.assertEqual(r['summary']['breaking'], 3)


if __name__ == '__main__': unittest.main()
