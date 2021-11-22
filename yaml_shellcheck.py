#!/usr/bin/env python3
#
# tool to run shellcheck on script-blocks in
# bitbucket-pipelines.yml or .gitlab-ci.yml config files
#
# Copyright (c) 2021, Martin Schütte <info@mschuette.name>

import abc
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


class GenericConfigObject(object):
    def __new__(cls, data, filename):
        return super().__new__(cls)

    @abc.abstractmethod
    def __init__(self, data, filename):
        logging.debug("GenericConfigObject.__init__() from %s", self.__class__.__name__)
        self.parsed_content = {}
        self.parsed_success = False
        self.input_filename = filename
        self.tmp_filenames = []

    def __repr__(self):
        class_name = type(self).__name__
        outstr = "{}(\n".format(class_name)
        for key in self.parsed_content:
            outstr += "  {}: {}\n".format(key, self.parsed_content[key])
        outstr += ")\n"
        return outstr

    def write_tmp_files(self, base_outdir, default_shell):
        """write script snippets into temporary files below base directory"""
        subdir = Path(base_outdir) / self.input_filename
        # remove all '..' elements from the tmp file paths
        if ".." in subdir.parts:
            parts = filter(lambda a: a != "..", list(subdir.parts))
            subdir = Path(*parts)
        subdir.mkdir(exist_ok=True, parents=True)

        for jobkey in self.parsed_content:
            scriptfilename = subdir / jobkey
            scriptfilename.parent.mkdir(exist_ok=True, parents=True)
            with open(scriptfilename, "w") as f:
                if not self.parsed_content[jobkey].startswith("#!"):
                    f.write(f"{default_shell}\n")
                f.write(self.parsed_content[jobkey])
                rel_filename = str(scriptfilename.relative_to(Path(base_outdir)))
                self.tmp_filenames.append(rel_filename)
                logger.debug("%s.write_tmp_files() wrote file %s",
                             type(self).__name__, rel_filename)


class BitbucketPipelineConfig(GenericConfigObject):
    """Bitbucket pipeline files are deeply nested, and they do not
    publish a schema, as a result we simply search all scripts elements,
    something like `pipelines.**.script`
    """

    @staticmethod
    def __get_scripts(data, path):
        results = {}
        if isinstance(data, dict):
            if "script" in data:
                script = data["script"]
                if isinstance(script, str):
                    results[f"{path}/script"] = script
                elif isinstance(script, list):
                    results[f"{path}/script"] = "\n".join(script)
            for key in data:
                results.update(BitbucketPipelineConfig.__get_scripts(data[key], f"{path}/{key}"))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                results.update(BitbucketPipelineConfig.__get_scripts(item, f"{path}/{i}"))
        elif (
            isinstance(data, str)
            or isinstance(data, int)
            or isinstance(data, float)
            or isinstance(data, None)
        ):
            pass
        return results

    def __init__(self, data, filename):
        super().__init__(data, filename)

        if "pipelines" not in data:
            self.parsed_content = {}
        else:
            self.parsed_content = self.__get_scripts(data["pipelines"], "pipelines")
        self.parsed_success = True


class GitHubActionsConfig(GenericConfigObject):
    """GitHub: from the docs the search pattern should be `jobs.<job_id>.steps[*].run`
    https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions

    as a simple first step we match on `jobs.**.run`
    """

    @staticmethod
    def __get_runs(data, path):
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
                results.update(GitHubActionsConfig.__get_runs(data[key], f"{path}/{key}"))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                results.update(GitHubActionsConfig.__get_runs(item, f"{path}/{i}"))
        elif (
            isinstance(data, str)
            or isinstance(data, int)
            or isinstance(data, float)
            or isinstance(data, None)
        ):
            pass
        return results

    def __init__(self, data, filename):
        super().__init__(data, filename)

        if "jobs" not in data:
            self.parsed_content = {}
        else:
            self.parsed_content = self.__get_runs(data["jobs"], "jobs")
        self.parsed_success = True


class CircleCiConfig(GenericConfigObject):
    """CircleCI: match on `jobs.*.steps.run`,
    https://circleci.com/docs/2.0/configuration-reference/
    """

    def __init__(self, data, filename):
        super().__init__(data, filename)

        if "jobs" not in data:
            self.parsed_content = {}
        else:
            self.parsed_content = self.__get_jobs(data)
        self.parsed_success = True

    @staticmethod
    def __get_jobs(data):
        result = {}
        for jobkey, job in data["jobs"].items():
            steps = job.get("steps", [])
            logging.debug("job %s: %s", jobkey, steps)
            for step_num, step in enumerate(steps):
                if not (isinstance(step, dict) and "run" in step):
                    logging.debug("job %s, step %d: no run declaration", jobkey, step_num)
                    continue
                run = step["run"]
                shell = None
                logging.debug("job %s, step %d: found %s %s", jobkey, step_num, type(run), run)
                # challenge: the run element can have different data types
                if isinstance(run, dict):
                    if "command" in run:
                        script = run["command"]
                        if "shell" in run:
                            shell = run["shell"]
                    else:
                        pass  # could be a directive like `save_cache`
                elif isinstance(run, str):
                    script = run
                elif isinstance(run, list):
                    script = "\n".join(run)
                else:
                    raise ValueError(f"unexpected data type {type(run)} in job {jobkey} step {step_num}")

                # CircleCI uses '<< foo >>' for context parameters,
                # we try to be useful and replace these with a simple shell variable
                script = re.sub(r'<<\s*([^\s>]*)\s*>>', r'"$PARAMETER"', script)
                # add shebang line if we saw a 'shell' attribute
                # TODO: we do not check for supported shell like we do in get_ansible_scripts
                # TODO: not sure what is the best handling of bash vs. sh as default here
                if not shell:
                    # CircleCI default shell, see doc "Default shell options"
                    shell = "/bin/bash"

                script = f"#!{shell}\n" + script
                result[f"{jobkey}/{step_num}"] = script
        return result


class DroneCiConfig(GenericConfigObject):
    """Drone CI has a simple file format, with all scripts in
    `lists in steps[].commands[]`, see https://docs.drone.io/yaml/exec/
    """
    def __init__(self, data, filename):
        super().__init__(data, filename)

        if "steps" not in data:
            self.parsed_content = {}
        else:
            self.parsed_content = self.__get_jobs(data)
        self.parsed_success = True

    @staticmethod
    def __get_jobs(data):
        result = {}
        jobkey = data.get("name", "unknown")
        for item in data["steps"]:
            section = item.get("name")
            result[f"{jobkey}/{section}"] = "\n".join(item.get("commands", []))
        return result


class GitLabConfig(GenericConfigObject):
    """GitLab is nice, as far as I can tell its files have a
    flat hierarchy with many small job entities"""

    def __init__(self, data, filename):
        super().__init__(data, filename)

        if "steps" not in data:
            self.parsed_content = {}
        else:
            self.parsed_content = self.__get_jobs(data)
        self.parsed_success = True

    @staticmethod
    def __flatten_nested_string_lists(data):
        """helper function"""
        if isinstance(data, str):
            return data
        elif isinstance(data, list):
            return "\n".join([GitLabConfig.__flatten_nested_string_lists(item) for item in data])
        else:
            raise ValueError(
                f"unexpected data type {type(data)} in script section: {data}"
            )

    @staticmethod
    def __get_jobs(data):
        result = {}
        for jobkey in data:
            if not isinstance(data[jobkey], dict):
                continue
            for section in ["script", "before_script", "after_script"]:
                if section in data[jobkey]:
                    script = data[jobkey][section]
                    result[f"{jobkey}/{section}"] = GitLabConfig.__flatten_nested_string_lists(script)
        return result


class AnsibleShellConfig(GenericConfigObject):
    """Ansible: read all `shell` tasks
    https://docs.ansible.com/ansible/2.9/modules/shell_module.html
    """

    @staticmethod
    def __get_shell_tasks(data, path):
        results = {}
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
                        raise ValueError(f"unexpected data in element {path}/{i}/{key}")

                    # we cannot evaluate Jinja templates
                    # at least try to be useful and replace every expression with a variable
                    # we do not handle Jinja statements like loops of if/then/else
                    script = re.sub(r"{{.*}}", "$JINJA_EXPRESSION", script)

                    # try to add shebang line from 'executable' if it looks like a shell
                    executable = task.get("args", {}).get("executable", None)
                    if executable and "sh" not in executable:
                        logging.debug(
                            f"unsupported shell %s, in %d/%s", executable, i, key
                        )
                        # ignore this task
                        continue
                    elif executable:
                        script = f"#!{executable}\n" + script
                    results[f"{path}/{i}/{key}"] = script
            if "tasks" in task:
                results.update(AnsibleShellConfig.__get_shell_tasks(task["tasks"], f"{path}/{i}"))
            if "block" in task:
                results.update(AnsibleShellConfig.__get_shell_tasks(task["block"], f"{path}/block-{i}"))
        return results

    def __init__(self, data, filename):
        super().__init__(data, filename)

        if isinstance(data, list):
            self.parsed_content = self.__get_shell_tasks(data, "root")
        self.parsed_success = True


def select_yaml_schema(data, filename):
    # try to determine CI system and file format,
    # returns the right class name
    if isinstance(data, dict) and "pipelines" in data:
        logging.info(f"read {filename} as Bitbucket Pipelines config...")
        return BitbucketPipelineConfig
    elif isinstance(data, dict) and "on" in data and "jobs" in data:
        logging.info(f"read {filename} as GitHub Actions config...")
        return GitHubActionsConfig
    elif isinstance(data, dict) and "version" in data and "jobs" in data:
        logging.info(f"read {filename} as CircleCI config...")
        return CircleCiConfig
    elif (
        isinstance(data, dict) and "steps" in data and "kind" in data and "type" in data
    ):
        logging.info(f"read {filename} as Drone CI config...")
        return DroneCiConfig
    elif isinstance(data, list):
        logging.info(f"read {filename} as Ansible file...")
        return AnsibleShellConfig
    elif isinstance(data, dict):
        # TODO: GitLab is the de facto default value, we should add more checks here
        logging.info(f"read {filename} as GitLab CI config...")
        return GitLabConfig
    else:
        raise ValueError(f"read {filename}, cannot determine CI tool from YAML structure")


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
    classname = select_yaml_schema(data, filename)
    return classname(data, filename)


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
    return proc


def cleanup_files(args):
    if args.keep:
        return
    else:
        shutil.rmtree(args.outdir)
        logger.debug("removed working dir %s", args.outdir)


if __name__ == "__main__":
    args = setup()

    filenames = []
    # config_objects = []
    for filename in args.files:
        try:
            this_config_object = read_yaml_file(filename)
            # config_objects.append(this_config_object)
            logger.debug("%s", this_config_object)
            this_config_object.write_tmp_files(args.outdir, args.shell)
            filenames.extend(this_config_object.tmp_filenames)
        except ValueError as e:
            # only log, then ignore the error
            logger.error("%s", e)
    logger.debug("wrote files: %s", filenames)
    check_proc_result = run_shellcheck(args, filenames)
    cleanup_files(args)
    # exit with shellcheck exit code
    sys.exit(check_proc_result.returncode if check_proc_result else 0)
