# yaml-shellcheck

Wrapper script to run [shellcheck](https://github.com/koalaman/shellcheck) on YAML CI-config files.
Currently supported formats are [Bitbucket Pipelines](https://bitbucket.org/product/features/pipelines) and [GitLab CI](https://docs.gitlab.com/ee/ci/yaml/gitlab_ci_yaml.html).

```text
$ ./yaml_shellcheck.py -h
usage: yaml_shellcheck.py [-h] [-o OUTDIR] [-k] [-d] [-s SHELL] [-c COMMAND] files [files ...]

run shellcheck on script blocks from .gitlab-ci.yml or bitbucket-pipelines.yml

positional arguments:
  files                 YAML files to read

optional arguments:
  -h, --help            show this help message and exit
  -o OUTDIR, --outdir OUTDIR
                        output directory (default: create temporary directory)
  -k, --keep            keep (do not delete) output directory
  -d, --debug           debug output
  -s SHELL, --shell SHELL
                        default shebang line to add to shell script snippets (default: '#!/bin/sh -e')
  -c COMMAND, --command COMMAND
                        shellcheck command to run (default: shellcheck)
```
