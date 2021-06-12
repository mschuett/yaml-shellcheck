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
    publish a schema"""
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
    if not "pipelines" in data:
        return result
    result = get_scripts(data["pipelines"], "pipelines")
    logging.debug("got scripts: %s", result)
    for key in result:
        logging.debug("%s: %s", key, result[key])
    return result


def get_github_scripts(data):
    """GitHub
    we only look for `jobs.<job_id>.steps[*].run` sections
    https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions
    """
    raise NotImplementedError("GitHub Actions are not supported yet")
    # result = {}
    # for job in data.get("jobs", []):
    #     pass
    # return result


def get_gitlab_scripts(data):
    """GitLab is nice, as far as I can tell its files have a
    flat hierarchy with many small job entities"""
    result = {}
    for jobkey in data:
        for section in ["script", "before_script", "after_script"]:
            if isinstance(data[jobkey], dict) and section in data[jobkey]:
                script = data[jobkey][section]
                if isinstance(script, str):
                    result[f"{jobkey}/{section}"] = script
                elif isinstance(script, list):
                    result[f"{jobkey}/{section}"] = "\n".join(script)
    return result


def select_yaml_schema(data):
    # try to determine CI system and file format,
    # returns the right get function
    if "pipelines" in data:
        logging.info("read as Bitbucket Pipelines config...")
        return get_bitbucket_scripts
    elif "on" in data and "jobs" in data:
        logging.info("read as GitHub Actions config...")
        return get_github_scripts
    else:
        logging.info("read as GitLab CI config...")
        return get_gitlab_scripts


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
    get_script_snippets = select_yaml_schema(data)
    return get_script_snippets(data)


def write_tmp_files(args, data):
    filelist = []
    outdir = Path(args.outdir)
    outdir.mkdir(exist_ok=True, parents=True)
    for filename in data:
        subdir = outdir / filename
        subdir.mkdir(exist_ok=True, parents=True)
        for jobkey in data[filename]:
            scriptfilename = subdir / jobkey
            scriptfilename.parent.mkdir(exist_ok=True, parents=True)
            with open(scriptfilename, "w") as f:
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
