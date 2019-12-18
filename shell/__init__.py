import argh
import tempfile
import collections
import contextlib
import logging
import os
import pool.thread
import random
import signal
import string
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

_max_lines_memory = os.environ.get('SHELL_RUN_MAX_LINES_MEMORY', 50 * 1024)

def _echo(cmd, logfn):
    logfn('$ %s [cwd=%s]' % (util.colors.yellow(cmd), os.getcwd()))

def _make_cmd(args):
    return ' '.join(map(str, args))

def _run(fn, *a, echo=False):
    cmd = _make_cmd(a)
    logfn = _get_logfn(echo or _state.get('echo') or _state.get('stream'))
    _echo(cmd, logfn)
    _echo(cmd, logging.debug)
    return fn(cmd, executable='/bin/bash', shell=True)

def check_output(*a, **kw):
    output = _run(subprocess.check_output, *a, **kw)
    try:
        output = output.decode('utf-8')
    except:
        logging.warn('failed to utf-8 decode output of cmd: %s', a)
    return output

def check_call(*a, **kw):
    return _run(subprocess.check_call, *a, **kw)

def call(*a, **kw):
    return _run(subprocess.call, *a, **kw)

# some notes on possible improvements: https://github.com/nathants/py-shell/blob/0a407c189f1fbf4f182be2c53a8116e66ca044a4/shell/__init__.py#L46
def run(*a,
        stream=None,
        echo=None,
        stdin='',
        popen=False,
        callback=None,
        warn=False,
        zero=False,
        quiet=None,
        raw_cmd=False,
        timeout=0,
        hide_stderr=False):
    start = time.time()
    stream = stream or _state.get('stream') and stream is not False
    logfn = _get_logfn(stream)
    cmd = _make_cmd(a)
    if (stream and echo is None) or echo or _state.get('echo') and echo is not False:
        _echo(cmd, _get_logfn(True))
    _echo(cmd, logging.debug)
    kw = {'stdout': subprocess.PIPE,
          'stderr': subprocess.PIPE,
          'stdin': subprocess.PIPE if stdin else subprocess.DEVNULL}
    if stdin and hasattr(stdin, 'read'):
        kw['stdin'] = stdin
    if hide_stderr:
        kw['stderr'] = subprocess.DEVNULL
    if raw_cmd:
        proc = subprocess.Popen(a, **kw)
    else:
        proc = subprocess.Popen(cmd, shell=True, executable='/bin/bash', **kw)
    if stdin and not hasattr(stdin, 'read'):
        proc.stdin.write(bytes(stdin, 'UTF-8'))
        proc.stdin.close()
    if popen:
        return proc
    stop = False
    @util.misc.exceptions_kill_pid
    def process_lines(name, buffer, lines):
        if buffer:
            def process(line):
                try:
                    line = line.decode('utf-8')
                except:
                    logging.warn('failed to utf-8 decode cmd: %s', cmd)
                else:
                    line = line.rstrip()
                    if line.strip():
                        logfn(line)
                        lines.append(line)
                    if callback:
                        callback(name, line)
            while not stop:
                line = buffer.readline()
                if not line:
                    break
                process(line)
            if len(lines) == _max_lines_memory:
                lines.appendleft(f'#### WARN shell.run() truncated output to the last {_max_lines_memory} lines ####')
    stdout_lines = collections.deque([], _max_lines_memory)
    stderr_lines = collections.deque([], _max_lines_memory)
    stderr_thread = pool.thread.new(process_lines, 'stderr', proc.stderr, stderr_lines)
    stdout_thread = pool.thread.new(process_lines, 'stdout', proc.stdout, stdout_lines)
    try:
        while True:
            exit = proc.poll()
            if exit is not None:
                break
            if timeout and time.time() - start > timeout:
                proc.terminate()
                raise AssertionError('\ntimed out after %s seconds from cmd: %s, cwd: %s' % (timeout, cmd, os.getcwd()))
            time.sleep(.01)
        stderr_thread.join()
        stdout_thread.join()
    finally:
        stop = True
    stderr = '\n'.join(stderr_lines)
    stdout = '\n'.join(stdout_lines)
    if warn:
        if not quiet:
            logfn('exit-code=%s from cmd: %s' % (proc.returncode, cmd))
        return {'stdout': stdout, 'stderr': stderr, 'exitcode': proc.returncode, 'cmd': cmd}
    elif zero:
        return proc.returncode == 0
    elif proc.returncode != 0:
        if quiet:
            sys.exit(proc.returncode)
        else:
            stdout = '' if stream else stdout
            raise AssertionError('\nstderr:\n%s\nstdout:\n%s\nexitcode=%s from cmd: %s, cwd: %s' % (stderr, stdout, proc.returncode, cmd, os.getcwd()))
    else:
        return stdout

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
            run('rm -rf', path)

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

set_echo = _set_state('echo')

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
def climb_git_root():
    orig = os.getcwd()
    while True:
        assert os.getcwd() != '/'
        if '.git' in dirs():
            break
        os.chdir('..')
    try:
        yield
    except:
        raise
    finally:
        os.chdir(orig)
