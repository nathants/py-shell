from unittest import mock
import os

import shell
import shell.conf


def test_get_or_prompt_pref():
    with shell.tempdir():
        with mock.patch('os.environ', {'HOME': os.getcwd()}):
            with mock.patch('builtins.input', mock.Mock(return_value='bar')) as _raw_input:
                assert shell.conf.get_or_prompt_pref('foo', __file__) == 'bar'
                assert _raw_input.call_count == 1
                assert shell.conf.get_or_prompt_pref('foo', __file__) == 'bar'
                assert _raw_input.call_count == 1
                with open(shell.files()[0]) as f:
                    assert f.read().strip() == 'foo: bar'
