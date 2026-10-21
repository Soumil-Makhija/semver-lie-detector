"""Differential checks against the interpreter, using only synthetic test functions."""
import inspect
import itertools
import unittest
from semver_lie_detector.compare import rejected_call


class RuntimeOracleTests(unittest.TestCase):
    def test_call_domain_predictions_match_python(self):
        forms = ['', 'x', 'x=1', 'x, /', 'x=1, /', 'x, y=1',
                 'x, *, y=1', 'x, *, y', '*args', '**kw',
                 'x=1, /, **kw', 'x, /, **kw', 'x, *args, **kw',
                 'x=1, y=2, *args, **kw', '*, x=1, **kw']
        functions = []
        for form in forms:
            namespace = {}
            # These fixed source strings are owned by this test, never user input.
            exec(f'def fixture({form}): pass', namespace)
            functions.append(namespace['fixture'])
        calls = []
        names = ['x', 'y', 'extra']
        for count in range(4):
            for size in range(len(names) + 1):
                for subset in itertools.combinations(names, size):
                    calls.append((list(range(count)), dict.fromkeys(subset, 'value')))

        def accepts(function, args, kwargs):
            try:
                function(*args, **kwargs)
                return True
            except TypeError:
                return False

        for i, old in enumerate(functions):
            for j, new in enumerate(functions):
                with self.subTest(before=forms[i], after=forms[j]):
                    witness, warning = rejected_call(inspect.signature(old), inspect.signature(new))
                    self.assertIsNone(warning)
                    expected = any(accepts(old, a, k) and not accepts(new, a, k) for a, k in calls)
                    self.assertEqual(bool(witness), expected)
                    if witness:
                        self.assertTrue(accepts(old, witness['args'], witness['kwargs']))
                        self.assertFalse(accepts(new, witness['args'], witness['kwargs']))
