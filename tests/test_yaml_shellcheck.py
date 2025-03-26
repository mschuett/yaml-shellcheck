import logging
import os
import pathlib
import re
import tempfile
import pytest
import glob

from yaml_shellcheck import main
import sys

class Capturing(list):
    regex = re.compile('.*(SC[0-9]{1,99}).*')

    def __enter__(self):
        self._temp = tempfile.NamedTemporaryFile('w+')
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = self._temp
        sys.stderr = self._temp
        return self

    def __exit__(self, *args):
        del self._temp
        sys.stdout = self._stdout
        sys.stderr = self._stderr

    def flush(self):
        self._temp.flush()
        self._temp.seek(0)
        lines = []
        for x in self._temp:
            lines.append(x)
        self._all = lines

    def all(self) -> list[str]:
        return self._all

    def shellcheck_errs(self) -> list[str]:
        return [re.findall(self.regex, x)[0] for x in self._all if re.match(self.regex, x) != None]

class Config():
    files: list[str] = []
    outdir: str
    shell: str = '#!/bin/sh -e'
    command: str = 'shellcheck'
    keep: bool = False

def get_test_data():
    return glob.glob('test-input/*.y*ml', include_hidden=True)

@pytest.mark.parametrize("test_data", get_test_data())
def test(test_data):
    args = Config()
    args.files = [test_data]
    args.outdir = tempfile.mkdtemp(prefix="py_yaml_shellcheck_")
    root: pathlib.Path = pathlib.Path(__file__).parent.parent.resolve()
    with open(root / (test_data + '.test_expected')) as f:
        expected = [line.strip() for line in f]

    with Capturing() as cap:
        main(args)
        cap.flush()
        ex = cap.shellcheck_errs()
        assert expected == ex