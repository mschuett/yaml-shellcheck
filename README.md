# yaml-shellcheck

[![Docker Repository on Quay](https://quay.io/repository/mschuette/yaml-shellcheck/status "Docker Repository on Quay")](https://quay.io/repository/mschuette/yaml-shellcheck)

Wrapper script to run [shellcheck](https://github.com/koalaman/shellcheck) on YAML CI-config files.
Currently supported formats are
[Bitbucket Pipelines](https://support.atlassian.com/bitbucket-cloud/docs/configure-bitbucket-pipelinesyml/),
[GitLab CI](https://docs.gitlab.com/ee/ci/yaml/gitlab_ci_yaml.html),
[GitHub Actions](https://docs.github.com/en/actions),
and (very limited) [Ansible](https://docs.ansible.com/ansible/2.9/modules/shell_module.html)

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

### GitLab CI

```yaml
lint_yaml_shellcheck:
  image:
    name: quay.io/mschuette/yaml-shellcheck:latest
    entrypoint: [""]
  script:
    - find . -name \*.yaml -or -name \*.yml | xargs python3 yaml_shellcheck.py
```

## File Formats

The main function of this tool is to encode which elements inside the YAML data
contain shell scripts. So far three formats are supported.

### Bitbucket Pipelines

Handling Bitbucket files is very simple. A file with a `pipelines` object
is read as a Bitbucket Pipeline file, and every `script` attribute inside
is considered a shell script.

### GitHub Actions

GitHub Actions are similar to Bitbucket. A file with a `jobs` object
is read as a GitHub Actions file, and every `run` attribute inside
is considered a shell script.

* `shell` attributes are not supported  
this is a todo, it should be simple enough to only check `sh` and `bash` scripts with right shebang line
* [expressions](https://docs.github.com/en/actions/reference/context-and-expression-syntax-for-github-actions) get replaced with a simple variable before running shellcheck

### GitLab CI Pipelines

GitLab CI files have more structure, and we try to support more of it.

* `script`, `before_script`, `after_script`: GitLab has not one, but three different shell script attributes which are read as three independent scripts. In GitLab `before_script` and `script` get concatenated and executed in a single shell process, whereas `after_script` always starts a new shell process. This has some implications for variable visibility etc. and is ignored in this tool.
* `include` is not supported, every YAML file is parsed on its own. For large pipelines with many includes you may want to use other tools to resolve all include and then run yaml_shellcheck on the merged YAML file.
* `!reference` is semi-supported, we only read the tag and insert a placeholder in order not to break the YAML parsing (todo, should be simple to improve).
* `variables` are supported experimentally, we try to read per-file and per-job variables and insert them into the shell script file. (To be honest, I am not sure this is actually useful, so I might remove that overhead in future versions.)

### Ansible

Ansible support is limited. This tool reads Ansible playbook or task files with YAML lists.

So far it recognizes three kinds of list elements:
* Tasks using the `shell` (or `ansible.builtin.shell`) [module](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/shell_module.html#ansible-collections-ansible-builtin-shell-module).
* Playbook elements, containing a `tasks` attribute.
* [Blocks](https://docs.ansible.com/ansible/latest/user_guide/playbooks_blocks.html) (`block`) for nested task lists.
* Jinja expressions (`{{ ... }}`) are ignored and replaced with placeholder shell variables.

### Common

Files are read with a YAML parser, so all YAML anchors are resolved.
There is no additional check on data types or structure.

Following the Bitbucket/GitLab usage a script block may contain a string or an
array of strings.
