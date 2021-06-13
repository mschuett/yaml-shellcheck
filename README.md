# yaml-shellcheck

Wrapper script to run [shellcheck](https://github.com/koalaman/shellcheck) on YAML CI-config files.
Currently supported formats are [Bitbucket Pipelines](https://support.atlassian.com/bitbucket-cloud/docs/configure-bitbucket-pipelinesyml/) and [GitLab CI](https://docs.gitlab.com/ee/ci/yaml/gitlab_ci_yaml.html).

## Usage

### Shell

Needs Python 3 with library [ruamel.yaml](https://pypi.org/project/ruamel.yaml/),
and shellcheck.

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

### Docker

```shell
# build image
$ docker build . -t yaml_shellcheck:latest
# run image
$ docker run -v `pwd`:/app yaml_shellcheck app/*.yaml
```
