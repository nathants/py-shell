import argh
import shutil
import tempfile
import collections
import contextlib
import logging
import os
import pool.thread
import signal
import subprocess
import sys
import termios
import time
import tty
import types
import util.cached
import util.colors
import util.misc
import util.strings

_max_lines_memory = os.environ.get('SHELL_RUN_MAX_LINES_MEMORY', 64 * 1024)

def _echo(cmd, logfn):
    logfn('$ %s [cwd=%s]' % (util.colors.yellow(cmd), os.getcwd()))

def _make_cmd(args):
    return 'set -eou pipefail; ' + ' '.join(map(str, args))

def _run(fn, *a, echo=False):
    cmd = _make_cmd(a)
    logfn = _get_logfn(echo or set.get('echo') or set.get('stream'))
    _echo(cmd, logfn)
    _echo(cmd, logging.debug)
    return fn(cmd, executable='/bin/bash', shell=True)

def check_output(*a, **kw):
    return _run(subprocess.check_output, *a, **kw).decode('utf-8')

def check_call(*a, **kw):
    return _run(subprocess.check_call, *a, **kw)

def call(*a, **kw):
    return _run(subprocess.call, *a, **kw)

def warn(*a, stdin=None, stdout=subprocess.PIPE, timeout=None):
    cwd = os.getcwd()
    cmd = _make_cmd(a)
    start = time.monotonic()
    _echo(cmd, logging.debug)
    if set.get('stream') or set.get('echo'):
        _echo(cmd, _get_logfn(True))
    stdin_bytes = None
    if isinstance(stdin, bytes):
        stdin_bytes = stdin
        stdin = subprocess.PIPE
    elif isinstance(stdin, str):
        stdin_bytes = stdin.encode()
        stdin = subprocess.PIPE
    proc = subprocess.Popen(
        cmd,
        shell=True,
        executable='/bin/bash',
        stdout=stdout,
        stderr=subprocess.PIPE,
        stdin=stdin or subprocess.DEVNULL,
    )
    if stdin_bytes:
        proc.stdin.write(stdin_bytes)
        proc.stdin.close()
    if stdout == subprocess.PIPE:
        stdout = collections.deque([], _max_lines_memory)
        while True:
            assert not timeout or time.monotonic() - start < timeout, f'timed out after {timeout} seconds from cmd: {cmd}, cwd: {cwd}'
            line = proc.stdout.readline()
            if not line:
                break
            stdout.append(line.decode())
    while True:
        assert not timeout or time.monotonic() - start < timeout, f'timed out after {timeout} seconds from cmd: {cmd}, cwd: {cwd}'
        exit = proc.poll()
        if exit is not None:
            break
        time.sleep(.01)
    try:
        stdout = ''.join(stdout).rstrip()
    except TypeError:
        stdout = None
    return {'exitcode': exit, 'stdout': stdout, 'stderr': proc.stderr.read().decode().rstrip(), 'cmd': cmd, 'cwd': cwd}

def run(*a,
        stream=None,
        echo=None,
        stdin='',
        callback=None,
        warn=False,
        raw_cmd=False,
        timeout=0):
    start = time.monotonic()
    stream = stream or set.get('stream') and stream is not False
    logfn = _get_logfn(stream)
    cmd = _make_cmd(a)
    if (stream and echo is None) or echo or set.get('echo') and echo is not False:
        _echo(cmd, _get_logfn(True))
    _echo(cmd, logging.debug)
    kw = {'stdout': subprocess.PIPE,
          'stderr': subprocess.PIPE,
          'stdin': subprocess.PIPE if stdin else subprocess.DEVNULL}
    cwd = os.getcwd()
    if stdin and hasattr(stdin, 'read'):
        kw['stdin'] = stdin
    if raw_cmd:
        proc = subprocess.Popen(a, **kw)
    else:
        proc = subprocess.Popen(cmd, shell=True, executable='/bin/bash', **kw)
    if stdin and not hasattr(stdin, 'read'):
        proc.stdin.write(bytes(stdin, 'utf-8'))
        proc.stdin.close()
    stop = False
    @util.misc.exceptions_kill_pid
    def process_lines(name, buffer, lines):
        while not stop:
            line = buffer.readline()
            if not line:
                break
            try:
                line = line.decode('utf-8').rstrip()
            except:
                logging.warn('failed to utf-8 decode cmd: %s', cmd)
            else:
                logfn(line)
                lines.append(line)
                if callback:
                    callback(name, line)
    stdout_lines = collections.deque([], _max_lines_memory)
    stderr_lines = collections.deque([], _max_lines_memory)
    stderr_thread = pool.thread.new(process_lines, 'stderr', proc.stderr, stderr_lines)
    stdout_thread = pool.thread.new(process_lines, 'stdout', proc.stdout, stdout_lines)
    try:
        while True:
            assert not timeout or time.monotonic() - start < timeout, f'timed out after {timeout} seconds from cmd: {cmd}, cwd: {cwd}'
            exit = proc.poll()
            if exit is not None:
                break
            time.sleep(.01)
        stderr_thread.join()
        stdout_thread.join()
    finally:
        stop = True
    stderr = '\n'.join(stderr_lines)
    stdout = '\n'.join(stdout_lines)
    if warn:
        return {'stdout': stdout, 'stderr': stderr, 'exitcode': proc.returncode, 'cmd': cmd}
    elif proc.returncode != 0:
        print(stderr, file=sys.stderr)
        print(stdout, flush=True)
        print(f'{cmd} [exitcode={proc.returncode} cwd={cwd}]', file=sys.stderr, flush=True)
        raise ExitCode(proc.returncode, stdout, stderr)
    else:
        return stdout

class ExitCode(Exception):
    pass

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
def cd(path='.', mkdir=True):
    orig = os.path.abspath(os.getcwd())
    if path:
        path = os.path.expanduser(path)
        if not os.path.isdir(path) and mkdir:
            os.makedirs(path)
        os.chdir(path)
    try:
        yield
    except:
        raise
    finally:
        os.chdir(orig)

@contextlib.contextmanager
def tempdir(cleanup=True, intemp=True):
    if intemp:
        path = tempfile.mkdtemp()
    else:
        path = tempfile.mkdtemp(dir='.')
    try:
        with cd(path):
            yield path
    except:
        raise
    finally:
        if cleanup:
            assert path != '/', 'fatal: cannot rm /'
            shutil.rmtree(path)

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
        text = util.strings.b64_encode(text)
        cmd = 'echo %(text)s | base64 -d | less -cR' % locals()
        check_call(cmd)

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

set = {} # define "stream" or "echo" to any value to enable those without using the context managers of the same name

def _set(key):
    @contextlib.contextmanager
    def fn():
        orig = set.get(key)
        set[key] = True
        try:
            yield
        except:
            raise
        finally:
            if orig is not None:
                set[key] = orig
            else:
                del set[key]
    return fn

set_stream = _set('stream')
stream     = _set('stream')
set_echo = _set('echo')
echo     = _set('echo')

def _get_logfn(should_log):
    def fn(x):
        if should_log:
            if hasattr(logging.root, '_ready'):
                logging.info(x)
            else:
                sys.stderr.write(x.rstrip() + '\n')
                sys.stderr.flush()
    return fn

def ignore_closed_pipes():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

def getch():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        val = sys.stdin.read(1).lower()
        if val == '\x03':
            sys.exit(1)
        else:
            return val
    except KeyboardInterrupt:
        sys.exit(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

@contextlib.contextmanager
def climb_until_exists(path):
    orig = os.getcwd()
    try:
        while True:
            assert os.getcwd() != '/'
            if os.path.exists(path):
                break
            os.chdir('..')
        yield
    except:
        raise
    finally:
        os.chdir(orig)

@contextlib.contextmanager
def climb_git_root():
    with climb_until_exists('.git'):
        yield
