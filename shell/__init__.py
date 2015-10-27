import argh
import collections
import contextlib
import logging
import os
import random
import util.cached
import util.colors
import util.hacks
import signal
import string
import subprocess
import sys
import types


_max_lines_stdout_cached = 1000


def _echo(cmd, logfn):
    logfn('$(%s) [cwd=%s]' % (util.colors.yellow(cmd), os.getcwd()))


def _make_cmd(args, stdin):
    cmd = ' '.join(map(str, args))
    if stdin:
        with tempdir(cleanup=False):
            path = os.path.abspath('stdin')
            with open(path, 'w') as f:
                f.write(stdin)
        cmd = 'cat %(path)s | %(cmd)s' % locals()
    return cmd


def _run(fn, *a, stdin=None, echo=False):
    cmd = _make_cmd(a, stdin)
    logfn = _get_logfn(echo or _state.get('stream'))
    _echo(cmd, logfn)
    return fn(cmd, **_call_kw)


def check_output(*a, **kw):
    return _run(subprocess.check_output, *a, **kw).decode('utf-8')


def check_call(*a, **kw):
    return _run(subprocess.check_call, *a, **kw)


def call(*a, **kw):
    return _run(subprocess.call, *a, **kw)


def run(*a, stream=False, echo=False, stdin='', popen=False, callback=None, warn=False, zero=False, quiet=False):
    stream = stream or _state.get('stream')
    logfn = _get_logfn(stream)
    cmd = _make_cmd(a, stdin)
    if (stream and echo is None) or echo:
        _echo(cmd, _get_logfn(True))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, **_call_kw)
    if popen:
        return proc
    output = _process_lines(proc, logfn, callback)
    if warn:
        logfn('exit-code=%s from cmd: %s' % (proc.returncode, cmd))
        return {'output': output, 'exitcode': proc.returncode, 'cmd': cmd}
    elif zero:
        return proc.returncode == 0
    elif proc.returncode != 0:
        if quiet:
            sys.exit(proc.returncode)
        else:
            output = '' if stream else output
            raise Exception('%s\nexitcode=%s from cmd: %s, cwd: %s' % (output, proc.returncode, cmd, os.getcwd()))
    else:
        return output


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
            run(sudo(), 'rm -rf', path)


def dispatch_commands(_globals, _name_):
    """
    dispatch all top level functions not starting with underscore
    >>> # dispatch_commands(globals(), __name__)
    """
    try:
        argh.dispatch_commands(sorted([
            v for k, v in _globals.items()
            if isinstance(v, types.FunctionType)
            and v.__module__ == _name_
            and not k.startswith('_')
            and k != 'main'
        ], key=lambda x: x.__name__))
    except KeyboardInterrupt:
        sys.exit(1)


def less(text):
    if text:
        check_call('less -cR', stdin=text)


@util.cached.func
def sudo():
    """
    used in place of "sudo", returns "sudo" if you can sudo, otherwise ""
    """
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


set_quiet = _set_state('quiet')


def _process_lines(proc, log, callback=None):
    lines = collections.deque(maxlen=_max_lines_stdout_cached)
    def process(line):
        line = util.hacks.stringify(line).rstrip()
        if line.strip():
            log(line)
            lines.append(line)
        if callback:
            callback(line)
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        process(line)
    proc.wait()
    return '\n'.join(lines)


def _get_logfn(should_log):
    def fn(x):
        if should_log:
            if hasattr(logging.root, '_ready'):
                logging.info(x)
            else:
                sys.stdout.write(x.rstrip() + '\n')
                sys.stdout.flush()
    return fn


_call_kw = {'shell': True, 'executable': '/bin/bash', 'stderr': subprocess.STDOUT}


def ignore_closed_pipes():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
