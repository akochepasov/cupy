import collections
import re
import textwrap
import unittest

import pytest

from cupy import testing


@testing.parameterize(
    {'actual': {'a': [1, 2], 'b': [3, 4, 5]},
     'expect': [{'a': 1, 'b': 3}, {'a': 1, 'b': 4}, {'a': 1, 'b': 5},
                {'a': 2, 'b': 3}, {'a': 2, 'b': 4}, {'a': 2, 'b': 5}]},
    {'actual': {'a': [1, 2]}, 'expect': [{'a': 1}, {'a': 2}]},
    {'actual': {'a': [1, 2], 'b': []}, 'expect': []},
    {'actual': {'a': []}, 'expect': []},
    {'actual': {}, 'expect': [{}]})
class ProductTest(unittest.TestCase):

    def test_product(self):
        self.assertListEqual(testing.product(self.actual), self.expect)


@testing.parameterize(
    {'actual': [[{'a': 1, 'b': 3}, {'a': 2, 'b': 4}], [{'c': 5}, {'c': 6}]],
     'expect': [{'a': 1, 'b': 3, 'c': 5}, {'a': 1, 'b': 3, 'c': 6},
                {'a': 2, 'b': 4, 'c': 5}, {'a': 2, 'b': 4, 'c': 6}]},
    {'actual': [[{'a': 1}, {'a': 2}], [{'b': 3}, {'b': 4}, {'b': 5}]],
     'expect': [{'a': 1, 'b': 3}, {'a': 1, 'b': 4}, {'a': 1, 'b': 5},
                {'a': 2, 'b': 3}, {'a': 2, 'b': 4}, {'a': 2, 'b': 5}]},
    {'actual': [[{'a': 1}, {'a': 2}]], 'expect': [{'a': 1}, {'a': 2}]},
    {'actual': [[{'a': 1}, {'a': 2}], []], 'expect': []},
    {'actual': [[]], 'expect': []},
    {'actual': [], 'expect': [{}]})
class ProductDictTest(unittest.TestCase):

    def test_product_dict(self):
        self.assertListEqual(testing.product_dict(*self.actual), self.expect)


def f(x):
    return x


class C(object):

    def __call__(self, x):
        return x

    def method(self, x):
        return x


@testing.parameterize(
    {'callable': f},
    {'callable': lambda x: x},
    {'callable': C()},
    {'callable': C().method}
)
class TestParameterize(unittest.TestCase):

    def test_callable(self):
        y = self.callable(1)
        self.assertEqual(y, 1)

    def test_skip(self):
        # Skipping the test case should not report error.
        self.skipTest('skip')


@testing.parameterize(
    {'param1': 1},
    {'param1': 2})
@testing.parameterize(
    {'param2': 3},
    {'param2': 4})
class TestParameterizeTwice(unittest.TestCase):
    # This test only checks if each of the parameterized combinations is a
    # member of the expected combinations. This test does not check if each
    # of the expected combinations is actually visited by the parameterization,
    # as there are no way to test that in a robust manner.

    def test_twice(self):
        assert hasattr(self, 'param1')
        assert hasattr(self, 'param2')
        assert (self.param1, self.param2) in (
            (1, 3),
            (1, 4),
            (2, 3),
            (2, 4))


# ##### Test _pytest_impl ##### #

# enable `testdir` fixture
pytest_plugins = "pytester",


@pytest.mark.parametrize(("src", "outcomes"), [
    (  # simple
        textwrap.dedent("""\
        @testing.parameterize({'a': 1}, {'a': 2})
        class TestA:
            def test_a(self):
                assert self.a > 0
        """), [
            ("::TestA::test_a[_param_0_{a=1}]", "PASSED"),
            ("::TestA::test_a[_param_1_{a=2}]", "PASSED"),
        ]
    ),
    (  # simple fail
        textwrap.dedent("""\
        @testing.parameterize({'a': 1}, {'a': 2})
        class TestA:
            def test_a(self):
                assert self.a == 1
        """), [
            ("::TestA::test_a[_param_0_{a=1}]", "PASSED"),
            ("::TestA::test_a[_param_1_{a=2}]", "FAILED"),
        ]
    ),
    (  # set of params can be different
        textwrap.dedent("""\
        @testing.parameterize({'a': 1}, {'b': 2})
        class TestA:
            def test_a(self):
                a = getattr(self, 'a', 3)
                b = getattr(self, 'b', 4)
                assert (a, b) in [(1, 4), (3, 2)]
        """), [
            ("::TestA::test_a[_param_0_{a=1}]", "PASSED"),
            ("::TestA::test_a[_param_1_{b=2}]", "PASSED"),
        ]
    ),
    (  # multiple params and class attr
        textwrap.dedent("""\
        @testing.parameterize({'a': 1, 'b': 4}, {'a': 2, 'b': 3})
        class TestA:
            c = 5
            def test_a(self):
                assert self.a + self.b == self.c
        """), [
            ("::TestA::test_a[_param_0_{a=1, b=4}]", "PASSED"),
            ("::TestA::test_a[_param_1_{a=2, b=3}]", "PASSED"),
        ]
    ),
    (  # combine pytest.mark.parameterize
        textwrap.dedent("""\
        import pytest
        @pytest.mark.parametrize("outer", ["E", "e"])
        @testing.parameterize({"x": "D"}, {"x": "d"})
        @pytest.mark.parametrize("inner", ["c", "C"])
        class TestA:
            @pytest.mark.parametrize(
                ("fn1", "fn2"), [("A", "b"), ("a", "B")])
            def test_a(self, fn2, inner, outer, fn1):
                assert (
                    (fn1 + fn2 + inner + self.x + outer).lower()
                    == "abcde")
            @pytest.mark.parametrize(
                "fn", ["A", "a"])
            def test_b(self, outer, fn, inner):
                assert sum(
                    c.isupper() for c in [fn, inner, self.x, outer]
                ) != 2
        """), [
            ("::TestA::test_a[A-b-c-_param_0_{x='D'}-E]", "PASSED"),
            ("::TestA::test_a[A-b-c-_param_0_{x='D'}-e]", "PASSED"),
            ("::TestA::test_a[A-b-c-_param_1_{x='d'}-E]", "PASSED"),
            ("::TestA::test_a[A-b-c-_param_1_{x='d'}-e]", "PASSED"),
            ("::TestA::test_a[A-b-C-_param_0_{x='D'}-E]", "PASSED"),
            ("::TestA::test_a[A-b-C-_param_0_{x='D'}-e]", "PASSED"),
            ("::TestA::test_a[A-b-C-_param_1_{x='d'}-E]", "PASSED"),
            ("::TestA::test_a[A-b-C-_param_1_{x='d'}-e]", "PASSED"),
            ("::TestA::test_a[a-B-c-_param_0_{x='D'}-E]", "PASSED"),
            ("::TestA::test_a[a-B-c-_param_0_{x='D'}-e]", "PASSED"),
            ("::TestA::test_a[a-B-c-_param_1_{x='d'}-E]", "PASSED"),
            ("::TestA::test_a[a-B-c-_param_1_{x='d'}-e]", "PASSED"),
            ("::TestA::test_a[a-B-C-_param_0_{x='D'}-E]", "PASSED"),
            ("::TestA::test_a[a-B-C-_param_0_{x='D'}-e]", "PASSED"),
            ("::TestA::test_a[a-B-C-_param_1_{x='d'}-E]", "PASSED"),
            ("::TestA::test_a[a-B-C-_param_1_{x='d'}-e]", "PASSED"),
            ("::TestA::test_b[A-c-_param_0_{x='D'}-E]", "PASSED"),
            ("::TestA::test_b[A-c-_param_0_{x='D'}-e]", "FAILED"),
            ("::TestA::test_b[A-c-_param_1_{x='d'}-E]", "FAILED"),
            ("::TestA::test_b[A-c-_param_1_{x='d'}-e]", "PASSED"),
            ("::TestA::test_b[A-C-_param_0_{x='D'}-E]", "PASSED"),
            ("::TestA::test_b[A-C-_param_0_{x='D'}-e]", "PASSED"),
            ("::TestA::test_b[A-C-_param_1_{x='d'}-E]", "PASSED"),
            ("::TestA::test_b[A-C-_param_1_{x='d'}-e]", "FAILED"),
            ("::TestA::test_b[a-c-_param_0_{x='D'}-E]", "FAILED"),
            ("::TestA::test_b[a-c-_param_0_{x='D'}-e]", "PASSED"),
            ("::TestA::test_b[a-c-_param_1_{x='d'}-E]", "PASSED"),
            ("::TestA::test_b[a-c-_param_1_{x='d'}-e]", "PASSED"),
            ("::TestA::test_b[a-C-_param_0_{x='D'}-E]", "PASSED"),
            ("::TestA::test_b[a-C-_param_0_{x='D'}-e]", "FAILED"),
            ("::TestA::test_b[a-C-_param_1_{x='d'}-E]", "FAILED"),
            ("::TestA::test_b[a-C-_param_1_{x='d'}-e]", "PASSED"),
        ]
    ),
])
def test_parameterize(testdir, src, outcomes):
    testdir.makepyfile("from cupy import testing\n" + src)
    result = testdir.runpytest('-v', '--tb=no')
    expected_lines = [
        ".*{} {}.*".format(re.escape(name), res)
        for name, res in outcomes
    ]
    result.stdout.re_match_lines(expected_lines)
    expected_count = collections.Counter(
        [res.lower() for _, res in outcomes]
    )
    result.assert_outcomes(**expected_count)
