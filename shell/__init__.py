from __future__ import absolute_import, print_function
import argh
import contextlib
import logging
import os
import random
import string
import subprocess
import types

import s.cached
import s.colors
import s.hacks


def run(*a, **kw):
    interactive = kw.pop('interactive', False)
    warn = kw.pop('warn', False)
    zero = kw.pop('zero', False)
    echo = kw.pop('echo', False)
    callback = kw.pop('callback', None)
    stream = kw.pop('stream', _state.get('stream', False))
    popen = kw.pop('popen', False)
    log_or_print = _get_log_or_print(stream or echo)
    cmd = ' '.join(map(str, a))
    log_or_print('$({}) [cwd={}]'.format(s.colors.yellow(cmd), os.getcwd()))
    if interactive:
        _interactive_func[warn](cmd, **_call_kw)
    elif popen:
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, **_call_kw)
    elif stream or warn or callback or zero:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, **_call_kw)
        output = _process_lines(proc, log_or_print, callback)
        if warn:
            log_or_print('exit-code={} from cmd: {}'.format(proc.returncode, cmd))
            return {'output': output, 'exitcode': proc.returncode, 'cmd': cmd}
        elif zero:
            return proc.returncode == 0
        elif proc.returncode != 0:
            output = '' if stream else output
            raise Exception('{}\nexitcode={} from cmd: {}, cwd: {}'.format(output, proc.returncode, cmd, os.getcwd()))
        return output
    else:
        return s.hacks.stringify(subprocess.check_output(cmd, **_call_kw).rstrip())


def listdir(path='.', abspath=False):
    return list_filtered(path, abspath, lambda *a: True)


def dirs(path='.', abspath=False):
    return list_filtered(path, abspath, os.path.isdir)


def files(path='.', abspath=False):
    return list_filtered(path, abspath, os.path.isfile)


def list_filtered(path, abspath, predicate):
    path = os.path.expanduser(path)
    resolve = lambda x: os.path.abspath(os.path.join(path, x))
    return [resolve(x) if abspath else x
            for x in sorted(os.listdir(path))
            if predicate(os.path.join(path, x))]


@contextlib.contextmanager
def cd(path='.'):
    orig = os.path.abspath(os.getcwd())
    if path:
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            run('mkdir -p', path)
        os.chdir(path)
    try:
        yield
    except:
        raise
    finally:
        os.chdir(orig)


@contextlib.contextmanager
def tempdir(cleanup=True, intemp=True):
    while True:
        try:
            letters = string.letters
        except AttributeError:
            letters = string.ascii_letters
        path = ''.join(random.choice(letters) for _ in range(20))
        path = os.path.join('/tmp', path) if intemp else path
        if not os.path.exists(path):
            break
    run('mkdir -p', path)
    try:
        with cd(path):
            yield path
    except:
        raise
    finally:
        if cleanup:
            run(_sudo(), 'rm -rf', path)


def dispatch_commands(_globals, _name_):
    argh.dispatch_commands(sorted([
        v for k, v in _globals.items()
        if isinstance(v, types.FunctionType)
        and v.__module__ == _name_
        and not k.startswith('_')
        and k != 'main'
    ], key=lambda x: x.__name__))


def less(text):
    if text:
        with tempdir():
            with open('_', 'w') as f:
                f.write(text + '\n\n')
            run('less -cR _', interactive=True)


@s.cached.func
def _sudo():
    try:
        run('sudo whoami')
        return 'sudo'
    except:
        return ''


_state = {}


def _set_state(key):
    @contextlib.contextmanager
    def fn():
        orig = _state.get(key)
        _state[key] = True
        try:
            yield
        except:
            raise
        finally:
            del _state[key]
            if orig is not None:
                _state[key] = orig
    return fn


set_stream = _set_state('stream')


def _process_lines(proc, log, callback=None):
    lines = []
    def process(line):
        line = s.hacks.stringify(line).rstrip()
        if line.strip():
            log(line)
            lines.append(line)
        if callback:
            callback(line)
    while proc.poll() is None:
        process(proc.stdout.readline())
    for line in proc.communicate()[0].strip().splitlines(): # sometimes the last line disappears
        process(line)
    return '\n'.join(lines)


def _get_log_or_print(should_log):
    def fn(x):
        if should_log:
            if hasattr(logging.root, '_ready'):
                logging.info(x)
            else:
                print(x)
    return fn


_interactive_func = {False: subprocess.check_call, True: subprocess.call}


_call_kw = {'shell': True, 'executable': '/bin/bash', 'stderr': subprocess.STDOUT}
