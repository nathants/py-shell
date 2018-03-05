import argh
import contextlib
import logging
import os
import random
import signal
import string
import subprocess
import sys
import termios
import tty
import types
import util.cached
import util.colors
import util.hacks
import util.strings


def _echo(cmd, logfn):
    logfn('$(%s) [cwd=%s]' % (util.colors.yellow(cmd), os.getcwd()))


def _make_cmd(args):
    return ' '.join(map(str, args))


def _run(fn, *a, echo=False):
    cmd = _make_cmd(a)
    logfn = _get_logfn(echo or _state.get('echo') or _state.get('stream'))
    _echo(cmd, logfn)
    _echo(cmd, logging.debug)
    return fn(cmd, executable='/bin/bash', shell=True)


def check_output(*a, **kw):
    return _run(subprocess.check_output, *a, **kw).decode('utf-8')


def check_call(*a, **kw):
    return _run(subprocess.check_call, *a, **kw)


def call(*a, **kw):
    return _run(subprocess.call, *a, **kw)

# TODO have an option for threaded runs that instead of prefixing and
# colorizing the output, it uses curses, and statically updates every threads
# stdout display. each thread gets a single line showing the current value of
# stdin. useful for when one threads output is drowning the others. # noqa

# TODO add a name and color kwarg, which activate the prefixing and line
# coloring for multiple threaded runs. color is a bool, and iterates over a
# global cycle of the colors.

# TODO actually just move all the threaded shell logic here. it doesnt belong
# in ec2. naming, colorizing, and keeping track of fails/successes.

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
        stream_only=False,
        hide_stderr=False):
    stream = stream or _state.get('stream') and stream is not False
    logfn = _get_logfn(stream)
    cmd = _make_cmd(a)
    if (stream and echo is None) or echo or _state.get('echo') and echo is not False:
        _echo(cmd, _get_logfn(True))
    _echo(cmd, logging.debug)
    kw = {'stdout': subprocess.PIPE,
          'stdin': subprocess.PIPE if stdin else subprocess.DEVNULL}
    if warn:
        kw['stderr'] = subprocess.PIPE
    if hide_stderr:
        kw['stderr'] = subprocess.DEVNULL
    if raw_cmd:
        proc = subprocess.Popen(a, **kw)
    else:
        proc = subprocess.Popen(cmd, shell=True, executable='/bin/bash', **kw)
    if stdin:
        proc.stdin.write(bytes(stdin, 'UTF-8'))
        proc.stdin.close()
    if popen:
        return proc
    output = _process_lines(proc, logfn, callback, stream_only)
    if warn:
        logfn('exit-code=%s from cmd: %s' % (proc.returncode, cmd))
        return {'stdout': output, 'stderr': proc.stderr.read().decode('utf-8').rstrip(), 'exitcode': proc.returncode, 'cmd': cmd}
    elif zero:
        return proc.returncode == 0
    elif proc.returncode != 0:
        if quiet:
            sys.exit(proc.returncode)
        else:
            output = '' if stream else output
            raise AssertionError('%s\nexitcode=%s from cmd: %s, cwd: %s' % (output, proc.returncode, cmd, os.getcwd()))
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


def _process_lines(proc, log, callback=None, stream_only=False):
    lines = []
    def process(line):
        line = line.decode('utf-8').rstrip()
        if line.strip():
            log(line)
            if not stream_only:
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
