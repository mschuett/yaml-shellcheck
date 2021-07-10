#!/usr/bin/env python3
#
# tool to run shellcheck on script-blocks in
# bitbucket-pipelines.yml or .gitlab-ci.yml config files
#
# Copyright (c) 2021, Martin Schütte <info@mschuette.name>

import argparse
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
import re
import sys

from ruamel.yaml import YAML

global logger


def setup():
    global logger
    parser = argparse.ArgumentParser(
        description="run shellcheck on script blocks from .gitlab-ci.yml or bitbucket-pipelines.yml",
    )
    parser.add_argument("files", nargs="+", help="YAML files to read")
    parser.add_argument(
        "-o",
        "--outdir",
        help="output directory (default: create temporary directory)",
        type=str,
    )
    parser.add_argument(
        "-k",
        "--keep",
        help="keep (do not delete) output directory",
        action="store_true",
    )
    parser.add_argument("-d", "--debug", help="debug output", action="store_true")
    parser.add_argument(
        "-s",
        "--shell",
        help="default shebang line to add to shell script snippets (default: '#!/bin/sh -e')",
        default="#!/bin/sh -e",
        type=str,
    )
    parser.add_argument(
        "-c",
        "--command",
        help="shellcheck command to run (default: shellcheck)",
        default="shellcheck",
        type=str,
    )
    args = parser.parse_args()

    # Enable logging
    console_handler = logging.StreamHandler()
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.DEBUG if args.debug else logging.INFO,
        handlers=[console_handler],
    )
    logger = logging.getLogger(__name__)

    if not args.outdir:
        args.outdir = tempfile.mkdtemp(prefix="py_yaml_shellcheck_")
        logger.debug("created working dir: %s", args.outdir)
    return args


def get_bitbucket_scripts(data):
    """Bitbucket pipeline files are deeply nested, and they do not
    publish a schema, as a result we simply search all scripts elements,
    something like `pipelines.**.script`
    """
    logging.debug("get_bitbucket_scripts()")

    def get_scripts(data, path):
        results = {}
        if isinstance(data, dict):
            if "script" in data:
                script = data["script"]
                if isinstance(script, str):
                    results[f"{path}/script"] = script
                elif isinstance(script, list):
                    results[f"{path}/script"] = "\n".join(script)
            for key in data:
                results.update(get_scripts(data[key], f"{path}/{key}"))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                results.update(get_scripts(item, f"{path}/{i}"))
        elif (
            isinstance(data, str)
            or isinstance(data, int)
            or isinstance(data, float)
            or isinstance(data, None)
        ):
            pass
        return results

    result = {}
    if "pipelines" not in data:
        return result
    result = get_scripts(data["pipelines"], "pipelines")
    logging.debug("got scripts: %s", result)
    for key in result:
        logging.debug("%s: %s", key, result[key])
    return result


def get_github_scripts(data):
    """GitHub: from the docs the search pattern should be `jobs.<job_id>.steps[*].run`
    https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions

    as a simple first step we match on `jobs.**.run`
    """

    def get_runs(data, path):
        results = {}
        if isinstance(data, dict):
            if "run" in data:
                script = data["run"]
                if not isinstance(script, str):
                    raise ValueError(
                        "unexpected format of 'run' element, expected string and found "
                        + type(script)
                    )

                # GitHub Actions uses '${{ foo }}' for context expressions,
                # we try to be useful and replace these with a simple shell variable
                script = re.sub(r"\${{.*}}", "$ACTION_EXPRESSION", script)

                results[f"{path}/run"] = script

            for key in data:
                results.update(get_runs(data[key], f"{path}/{key}"))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                results.update(get_runs(item, f"{path}/{i}"))
        elif (
            isinstance(data, str)
            or isinstance(data, int)
            or isinstance(data, float)
            or isinstance(data, None)
        ):
            pass
        return results

    result = {}
    if "jobs" not in data:
        return result
    result = get_runs(data["jobs"], "jobs")
    logging.debug("got scripts: %s", result)
    for key in result:
        logging.debug("%s: %s", key, result[key])
    return result


def get_gitlab_scripts(data):
    """GitLab is nice, as far as I can tell its files have a
    flat hierarchy with many small job entities"""

    def merge_variables(data, jobkey):
        """helper function, gather variable definition from file and job"""
        job_variables = data[jobkey].get("variables", {}) or {}
        merged_variables = data.get("variables", {})
        merged_variables.update(job_variables)
        logging.debug("in job %s, merged variables %s", jobkey, job_variables)
        return "".join(
            [f'export {key}="{value}"\n' for key, value in merged_variables.items()]
        )

    result = {}
    for jobkey in data:
        if not isinstance(data[jobkey], dict):
            continue

        # todo: only generate if job has a script
        variables_setup_script = merge_variables(data, jobkey)

        for section in ["script", "before_script", "after_script"]:
            if section not in data[jobkey]:
                continue
            # pre-init with variable setup
            result[f"{jobkey}/{section}"] = variables_setup_script
            # then add the "real" script block
            script = data[jobkey][section]
            if isinstance(script, str):
                result[f"{jobkey}/{section}"] += script
            elif isinstance(script, list):
                result[f"{jobkey}/{section}"] += "\n".join(script)
    return result


def get_ansible_scripts(data):
    """Ansible: read all `shell` tasks
    https://docs.ansible.com/ansible/2.9/modules/shell_module.html
    """

    result = {}
    if not isinstance(data, list):
        return result

    for i, task in enumerate(data):
        # look for simple and qualified collection names:
        for key in ["shell", "ansible.builtin.shell"]:
            if key in task:
                # may be a string or a dict
                if isinstance(task[key], str):
                    script = task[key]
                elif isinstance(task[key], dict) and "cmd" in task[key]:
                    script = task[key]["cmd"]
                else:
                    raise ValueError(f"unexpected data in element {i}/{key}")

                # we cannot evaluate Jinja templates
                # at least try to be useful and replace every expression with a variable
                # we do not handle Jinja statements like loops of if/then/else
                script = re.sub(r"{{.*}}", "$JINJA_EXPRESSION", script)

                # try to add shebang line from 'executable' if it looks like a shell
                executable = task.get("args", {}).get("executable", None)
                if executable and "sh" not in executable:
                    logging.debug(f"unsupported shell %s, in %d/%s", executable, i, key)
                    # ignore this task
                    continue
                elif executable:
                    script = f"#!{executable}\n" + script
                result[f"{i}/{key}"] = script
    logging.debug("got scripts: %s", result)
    for key in result:
        logging.debug("%s: %s", key, result[key])
    return result


def select_yaml_schema(data, filename):
    # try to determine CI system and file format,
    # returns the right get function
    if isinstance(data, dict) and "pipelines" in data:
        logging.info(f"read {filename} as Bitbucket Pipelines config...")
        return get_bitbucket_scripts
    elif isinstance(data, dict) and "on" in data and "jobs" in data:
        logging.info(f"read {filename} as GitHub Actions config...")
        return get_github_scripts
    elif isinstance(data, dict):
        logging.info(f"read {filename} as GitLab CI config...")
        return get_gitlab_scripts
    elif isinstance(data, list):
        logging.info(f"read {filename} as Ansible file...")
        return get_ansible_scripts
    else:
        raise ValueError("cannot determine CI tool from YAML structure")


def read_yaml_file(filename):
    """read YAML and return dict with job name and shell scripts"""
    global logger

    class GitLabReference(object):
        yaml_tag = "!reference"

        def __init__(self, obj, attr):
            self.obj = obj
            self.attr = attr

        def __str__(self):
            return f"# {self.yaml_tag}[{self.obj}, {self.attr}]"

        @classmethod
        def to_yaml(cls, representer, node):
            return representer.represent_scalar(
                cls.yaml_tag, "[{.obj}, {.attr}]".format(node, node)
            )

        @classmethod
        def from_yaml(cls, constructor, node):
            assert len(node.value) == 2
            return str(cls(node.value[0].value, node.value[1].value))

    yaml = YAML(typ="safe")
    yaml.register_class(GitLabReference)

    with open(filename, "r") as f:
        data = yaml.load(f)
    get_script_snippets = select_yaml_schema(data, filename)
    return get_script_snippets(data)


def write_tmp_files(args, data):
    filelist = []
    outdir = Path(args.outdir)
    outdir.mkdir(exist_ok=True, parents=True)
    for filename in data:
        subdir = outdir / filename
        # remove all '..' elements from the tmp file paths
        if ".." in subdir.parts:
            parts = filter(lambda a: a != "..", list(subdir.parts))
            subdir = Path(*parts)
        subdir.mkdir(exist_ok=True, parents=True)
        for jobkey in data[filename]:
            scriptfilename = subdir / jobkey
            scriptfilename.parent.mkdir(exist_ok=True, parents=True)
            with open(scriptfilename, "w") as f:
                if not data[filename][jobkey].startswith("#!"):
                    f.write(f"{args.shell}\n")
                f.write(data[filename][jobkey])
                rel_filename = str(scriptfilename.relative_to(outdir))
                filelist.append(rel_filename)
                logger.debug("wrote file %s", rel_filename)
    return filelist


def run_shellcheck(args, filenames):
    if not filenames:
        return
    shellcheck_command = args.command.split() + filenames
    logger.debug("Starting subprocess: %s", shellcheck_command)
    proc = subprocess.run(
        shellcheck_command,
        shell=False,
        stdout=sys.stdout,
        stderr=sys.stderr,
        cwd=args.outdir,
    )
    logger.debug("subprocess result: %s", proc)


def cleanup_files(args):
    if args.keep:
        return
    else:
        shutil.rmtree(args.outdir)
        logger.debug("removed working dir %s", args.outdir)


if __name__ == "__main__":
    args = setup()

    filenames = []
    for filename in args.files:
        result = {filename: read_yaml_file(filename)}
        logger.debug("%s", result)
        filenames.extend(write_tmp_files(args, result))
    run_shellcheck(args, filenames)
    cleanup_files(args)
