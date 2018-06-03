import os
import util.dicts
import sys
import pytest

import shell


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


def test_output_run():
    assert 'asdf' == shell.run('echo asdf')


def test_exitcode_run():
    assert 1 == shell.run('false', warn=True)['exitcode']


def test_stdin():
    assert 'asdf' == shell.run('cat -', stdin='asdf')


def test_excepts_run():
    with pytest.raises(Exception):
        shell.run('false')

def test_callback():
    val = []
    shell.run('echo asdf', callback=lambda x: val.append(x))
    assert 'asdf' in val

def test_stdout_stderr():
    assert {'stderr': 'err', 'stdout': 'out'} == util.dicts.take(shell.run('echo out; echo err >&2', warn=True), ['stderr', 'stdout'])
    assert {'stderr': '',    'stdout': 'out'} == util.dicts.take(shell.run('echo out', warn=True), ['stderr', 'stdout'])
    assert {'stderr': 'err', 'stdout': ''}    == util.dicts.take(shell.run('echo err >&2', warn=True), ['stderr', 'stdout'])
