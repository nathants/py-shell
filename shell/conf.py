import os.path
import yaml
import logging


def _pref_path(_file_):
    _file_ = os.path.abspath(os.path.expanduser(_file_))
    name = '.{}.{}.{}.yaml'.format(*map(os.path.basename, [
        os.path.dirname(os.path.dirname(_file_)),
        os.path.dirname(_file_),
        _file_.split('.py')[0],
    ]))
    return os.path.join(os.environ['HOME'], name)


def get_or_prompt_pref(key, _file_, default=None, message=None):
    path = _pref_path(_file_)
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except IOError:
        data = {}
    if key not in data:
        message = message or key
        default = 'or default: {}'.format(default) if default else ''
        data[key] = input('preference value for "{message}" {default}? '.format(**locals()))
        with open(path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False)
    logging.debug('using preference %s for key %s from files %s', data[key], key, path)
    return data[key]


def get_optional_pref(key, _file_, default=None):
    path = _pref_path(_file_)
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except IOError:
        data = {}
    return data.get(key, default)
