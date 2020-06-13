import os
import util.time
import util.dicts
import sys
import pytest
import shell
from unittest import mock

def setup_module():
    globals()['_keys'] = list(sys.modules.keys())

def setup_function(fn):
    fn.ctx = shell.tempdir()
    fn.ctx.__enter__()
    for k, v in list(sys.modules.items()):
        if k not in globals()['_keys']:
            del sys.modules[k]
    sys.path.insert(0, os.getcwd())

def teardown_function(fn):
    fn.ctx.__exit__(None, None, None)
    sys.path.pop(0)

def test_tempdir():
    orig = os.getcwd()

    with shell.tempdir():
        path = os.getcwd()
        assert orig != path
        assert path.startswith('/tmp/')
    assert not os.path.isdir(path)

    with shell.tempdir(intemp=False):
        path = os.getcwd()
        assert orig != path
        assert path.startswith(f'{orig}/')
    assert not os.path.isdir(path)

    with shell.tempdir(cleanup=False):
        path = os.getcwd()
    try:
        assert os.path.isdir(path)
    finally:
        assert path != '/'
        shell.run('rm -rf', path)

def test_output_run():
    assert 'asdf' == shell.run('echo asdf')

def test_exitcode_run():
    assert 1 == shell.run('false', warn=True)['exitcode']

def test_stdin():
    assert 'asdf' == shell.run('cat -', stdin='asdf')

def test_excepts_run():
    with pytest.raises(SystemExit):
        shell.run('false')

def test_callback():
    val = []
    shell.run('echo asdf; echo 123 1>&2', callback=lambda name, x: val.append([name, x]))
    assert sorted(val) == sorted([['stdout', 'asdf'], ['stderr', '123']])

def test_stdout_stderr():
    assert {'stderr': 'err', 'stdout': 'out'} == util.dicts.take(shell.run('echo out; echo err >&2', warn=True), ['stderr', 'stdout'])
    assert {'stderr': '',    'stdout': 'out'} == util.dicts.take(shell.run('echo out', warn=True), ['stderr', 'stdout'])
    assert {'stderr': 'err', 'stdout': ''}    == util.dicts.take(shell.run('echo err >&2', warn=True), ['stderr', 'stdout'])

def test_max_lines():
    cmd = 'for i in {1..4}; do echo foo$i; done'
    f = lambda: [x.split()[0] for x in shell.run(cmd).splitlines()]
    assert f() == ['foo1', 'foo2', 'foo3', 'foo4']
    with mock.patch('shell._max_lines_memory', 3):
        assert f() == ['foo2', 'foo3', 'foo4']

def test_timeout():
    with util.time.timer() as t:
        with pytest.raises(AssertionError):
            shell.run('sleep 3; echo foo', timeout=1)
    assert int(t['seconds']) == 1

def test_warn():
    assert shell.warn('false') == {'exitcode': 1, 'stderr': '', 'stdout': ''}
    assert shell.warn('true')  == {'exitcode': 0, 'stderr': '', 'stdout': ''}
    assert shell.warn('echo a; echo b 1>&2; exit 3')  == {'exitcode': 3, 'stderr': 'b', 'stdout': 'a'}
    assert shell.warn('echo a; echo b 1>&2; exit 3', stdout=None)  == {'exitcode': 3, 'stderr': 'b', 'stdout': None}
