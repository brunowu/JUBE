# JUBE Benchmarking Environment
# Copyright (C) 2008-2024
# Forschungszentrum Juelich GmbH, Juelich Supercomputing Centre
# http://www.fz-juelich.de/jsc/jube
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""CLI program"""

from __future__ import (print_function,
                        unicode_literals,
                        division)

import jube2.jubeio
import jube2.util.util
import jube2.util.output
import jube2.conf
import jube2.info
import jube2.help
import jube2.log
import jube2.completion

import sys
import os
import re
import shutil
from jube2.util.version import StrictVersion

try:
    from urllib.request import urlopen
except ImportError:
    from urllib import urlopen

try:
    import argparse
except ImportError:
    print("argparse module not available; either install it "
          "(https://pypi.python.org/pypi/argparse), or "
          "switch to a Python version that includes it.")
    sys.exit(1)

LOGGER = jube2.log.get_logger(__name__)


def continue_benchmarks(args):
    """Continue benchmarks"""
    found_benchmarks = search_for_benchmarks(args)
    jube2.conf.HIDE_ANIMATIONS = args.hide_animation
    for benchmark_folder in found_benchmarks:
        _continue_benchmark(benchmark_folder, args)


def status(args):
    """Show benchmark status"""
    found_benchmarks = search_for_benchmarks(args)
    for benchmark_folder in found_benchmarks:
        benchmark = _load_existing_benchmark(args, benchmark_folder,
                                             load_analyse=False)
        if benchmark is None:
            return
        jube2.info.print_benchmark_status(benchmark)
        
def output(args):
    """Show output filename"""
    found_workpackages = list()
    stdout_paths = set()
    stderr_paths = set()
    paths = set()
    found_workpackages = search_for_workpackage(args, True)

    for wp in found_workpackages:
        #create parameter dictionary
        param_dict = dict()
        #all parameter from the benchmark
        for param_set in wp.benchmark.parametersets.values():
            for param in param_set.all_parameters:
                param_dict[param.name] = param.value
        #all jube parameter from the workpackage
        for param in wp.get_jube_parameterset():
            param_dict[param.name] = param.value
        #all jube parameter from the benchmark
        for param in wp.benchmark.get_jube_parameterset():
            param_dict[param.name] = param.value

        #create work directory
        if wp.step.alt_work_dir is None:
            work_dir = [os.getcwd(), wp.work_dir]
        else:
            dir_cache = jube2.util.util.substitution(wp.step.alt_work_dir,
                                                     param_dict)
            dir_cache = os.path.expandvars(os.path.expanduser(dir_cache))
            work_dir = [os.getcwd(), dir_cache]

        for operation in wp.step.operations:
            if operation.stdout_filename is not None:
                stdout_filename = jube2.util.util.substitution(
                    operation.stdout_filename, param_dict)
                stdout_filename = \
                    os.path.expandvars(os.path.expanduser(stdout_filename))
            else:
                stdout_filename = "stdout"

            work_dir.append(stdout_filename)
            stdout_paths.add(os.path.join(*work_dir))
            work_dir.remove(stdout_filename)

            if operation.stderr_filename is not None:
                stderr_filename = jube2.util.util.substitution(
                    operation.stderr_filename, param_dict)
                stderr_filename = \
                    os.path.expandvars(os.path.expanduser(stderr_filename))
            else:
                stderr_filename = "stderr"
            work_dir.append(stderr_filename)
            stderr_paths.add(os.path.join(*work_dir))
            work_dir.remove(stderr_filename)

    #show only error or done file
    if args.only:
        if args.only == "stdout":
            paths.update(stdout_paths)
        else:
            paths.update(stderr_paths)
    else:
        paths.update(stdout_paths)
        paths.update(stderr_paths)

    #sort paths
    paths = sorted(paths)

    #show conten of file, not only filename
    if args.display:
        for path in paths:
            LOGGER.info(path + "\n")
            file = open(path)
            LOGGER.info(file.read() + "\n")
    else:
        for path in paths:
            LOGGER.info(path + "\n")

def benchmarks_results(args):
    """Show benchmark results"""
    found_benchmarks = search_for_benchmarks(args)
    result_list = list()

    # Start with the newest benchmark to set the newest result configuration
    found_benchmarks.reverse()
    cnt = 0
    for benchmark_folder in found_benchmarks:
        if (args.num is None) or (cnt < args.num):
            result_list = _benchmark_result(benchmark_folder=benchmark_folder,
                                            args=args,
                                            result_list=result_list)
            cnt += 1
    for result_data in result_list:
        result_data.create_result(reverse=args.reverse)


def analyse_benchmarks(args):
    """Analyse benchmarks"""
    found_benchmarks = search_for_benchmarks(args)
    for benchmark_folder in found_benchmarks:
        _analyse_benchmark(benchmark_folder, args)


def remove_benchmarks(args):
    """Remove benchmarks or workpackages"""
    if(args.workpackage is not None):
        # If a workpackage id is provided by the user, only specific
        # workpackages will be removed
        found_workpackages = search_for_workpackage(args)
        for workpackage in found_workpackages:
            _remove_workpackage(workpackage, args)
    else:
        # Delete complete benchmarks
        found_benchmarks = search_for_benchmarks(args)
        for benchmark_folder in found_benchmarks:
            _remove_benchmark(benchmark_folder, args)


def command_help(args):
    """Show command help"""
    subparser = _get_args_parser()[1]
    if args.command is None:
        subparser["help"].print_help()
    elif args.command.lower() == "all":
        for key in sorted(jube2.help.HELP.keys()):
            print("{0}:".format(key))
            print(jube2.help.HELP[key])
    else:
        if args.command in jube2.help.HELP:
            if args.command in subparser:
                subparser[args.command].print_help()
            else:
                print(jube2.help.HELP[args.command])
        else:
            print("no help found for {0}".format(args.command))
            subparser["help"].print_help()


def info(args):
    """Benchmark information"""
    if args.id is None:
        if args.step is not None or args.workpackage is not None:
                LOGGER.warning("The -s and -w options are ignored if no "
                               "benchmark ID is given. Information for all "
                               "benchmarks is printed out.")
        jube2.info.print_benchmarks_info(args.dir)
    else:
        found_benchmarks = search_for_benchmarks(args)
        for benchmark_folder in found_benchmarks:
            benchmark = \
                _load_existing_benchmark(args, benchmark_folder,
                                         load_analyse=False)
            if benchmark is None:
                continue
            if args.step is None and args.workpackage is None:
                jube2.info.print_benchmark_info(benchmark)
            elif args.workpackage is None:
                # Display step information
                if args.step:
                    steps = args.step
                else:
                    steps = benchmark.steps.keys()
                # Set default csv_parametrization value to allow empty -c
                # option
                if args.csv_parametrization is None:
                    args.csv_parametrization = ","
                for step_name in steps:
                    jube2.info.print_step_info(
                        benchmark, step_name,
                        parametrization_only=args.parametrization,
                        parametrization_only_csv=args.csv_parametrization)
            else:
                # Display workpackage information
                if args.step:
                    steps = args.step
                else:
                    steps = benchmark.steps.keys()
                if args.workpackage:
                    wp_ids = [int(id) for id in args.workpackage]
                else:
                    wp_ids = [wp.id for wps in benchmark.workpackages.values()
                                    for wp in wps]
                for wp_id in wp_ids:
                    workpackage = benchmark.workpackage_by_id(wp_id)
                    if workpackage:
                        if workpackage.step.name in steps:
                            jube2.info.print_workpackage_info(benchmark, workpackage)
                        else:
                            LOGGER.warning("Workpackage with ID is ignored for "
                                           "further execution. It was not found in "
                                           "the specified steps.".format(wp_id))
                    else:
                        LOGGER.warning("Workpackage with ID is ignored for "
                                       "further execution. It was not found in "
                                       "the specified benchmark.".format(wp_id))

def update_check(args):
    """Check if a newer JUBE version is available."""
    try:
        website = urlopen(jube2.conf.UPDATE_VERSION_URL)
        version = website.read().decode().strip()
        if StrictVersion(jube2.conf.JUBE_VERSION) >= StrictVersion(version):
            LOGGER.info("Newest JUBE version {0} is already "
                        "installed.".format(jube2.conf.JUBE_VERSION))
        else:
            LOGGER.info(("Newer JUBE version {0} is available. "
                         "Currently installed version is {1}.\n"
                         "New version can be "
                         "downloaded here: {2}").format(
                version, jube2.conf.JUBE_VERSION,
                jube2.conf.UPDATE_URL))
    except IOError as ioe:
        raise IOError("Cannot connect to {0}: {1}".format(
            jube2.conf.UPDATE_VERSION_URL, str(ioe)))
    except ValueError as verr:
        raise ValueError("Cannot read version string from {0}: {1}".format(
            jube2.conf.UPDATE_VERSION_URL, str(verr)))


def show_log(args):
    """Show logs for benchmarks"""
    found_benchmarks = search_for_benchmarks(args)
    for benchmark_folder in found_benchmarks:
        show_log_single(args, benchmark_folder)


def show_log_single(args, benchmark_folder):
    """Show logs for a single benchmark"""
    # Find available logs
    available_logs = jube2.log.search_for_logs(benchmark_folder)

    # Use all available logs if none is selected ...
    if not args.command:
        matching = available_logs
        not_matching = list()
    # ... otherwise find intersection between available and
    # selected
    else:
        matching, not_matching = jube2.log.matching_logs(
            args.command, available_logs)

    # Output the log file
    for log in matching:
        jube2.log.log_print("BenchmarkID: {0} | Log: {1}".format(
            int(os.path.basename(benchmark_folder)), log))
        jube2.log.safe_output_logfile(log)

    # Inform user if any selected log was not found
    if not_matching:
        jube2.log.log_print("Could not find logs: {0}".format(
            ",".join(not_matching)))


def complete(args):
    """Handle shell completion"""
    jube2.completion.complete_function_bash(args)


def _load_existing_benchmark(args, benchmark_folder, restore_workpackages=True,
                             load_analyse=True):
    """Load an existing benchmark, given by directory benchmark_folder."""

    jube2.log.change_logfile_name(os.path.join(
        benchmark_folder, jube2.conf.LOGFILE_PARSE_NAME))

    # Add log information
    LOGGER.debug("Command: {0} {1}".format(
        os.path.basename(sys.argv[0]), " ".join(sys.argv[1:])))
    LOGGER.debug("Version: {0}".format(jube2.conf.JUBE_VERSION))

    # Read existing benchmark configuration
    try:
        parser = jube2.jubeio.Parser(os.path.join(
            benchmark_folder, jube2.conf.CONFIGURATION_FILENAME),
            force=args.force, strict=args.strict)
        benchmarks = parser.benchmarks_from_xml()[0]
    except IOError as exeption:
        LOGGER.warning(str(exeption))
        return None

    # benchmarks can be None if version conflict was blocked
    if benchmarks is not None:
        # Only one single benchmark exist inside benchmarks
        benchmark = list(benchmarks.values())[0]
    else:
        return None

    # Restore old benchmark id
    benchmark.id = int(os.path.basename(benchmark_folder))

    if restore_workpackages:
        # Read existing workpackage information
        try:
            parser = jube2.jubeio.Parser(os.path.join(
                benchmark_folder, jube2.conf.WORKPACKAGES_FILENAME),
                force=args.force, strict=args.strict)
            workpackages, work_stat = parser.workpackages_from_xml(benchmark)
        except IOError as exeption:
            LOGGER.warning(str(exeption))
            return None
        benchmark.set_workpackage_information(workpackages, work_stat)

    if load_analyse and os.path.isfile(os.path.join(
            benchmark_folder, jube2.conf.ANALYSE_FILENAME)):
        # Read existing analyse data
        parser = jube2.jubeio.Parser(os.path.join(
            benchmark_folder, jube2.conf.ANALYSE_FILENAME),
            force=args.force, strict=args.strict)
        analyse_result = parser.analyse_result_from_xml()
        if analyse_result is not None:
            for analyser in benchmark.analyser.values():
                if analyser.name in analyse_result:
                    analyser.analyse_result = analyse_result[analyser.name]

    jube2.log.only_console_log()

    return benchmark


def manipulate_comments(args):
    """Manipulate benchmark comment"""
    found_benchmarks = search_for_benchmarks(args)
    for benchmark_folder in found_benchmarks:
        _manipulate_comment(benchmark_folder, args)


def search_for_benchmarks(args):
    """Search for existing benchmarks"""
    found_benchmarks = list()
    if not os.path.isdir(args.dir):
        raise OSError("Not a directory: \"{0}\"".format(args.dir))
    all_benchmarks = [
        os.path.join(args.dir, directory)
        for directory in os.listdir(args.dir)
        if os.path.isdir(os.path.join(args.dir, directory))]
    all_benchmarks.sort()
    if (args.id is not None) and ("all" not in args.id):
        for benchmark_id in args.id:
            if benchmark_id == "last":
                benchmark_id = jube2.util.util.get_current_id(args.dir)
            # Search for existing benchmark
            benchmark_id = int(benchmark_id)
            if benchmark_id < 0:
                benchmark_id = int(
                    os.path.basename(all_benchmarks[benchmark_id]))
            benchmark_folder = jube2.util.util.id_dir(args.dir, benchmark_id)
            if not os.path.isdir(benchmark_folder):
                raise OSError("Benchmark directory not found: \"{0}\""
                              .format(benchmark_folder))
            if not os.path.isfile(os.path.join(
                    benchmark_folder, jube2.conf.CONFIGURATION_FILENAME)):
                LOGGER.warning(("Configuration file \"{0}\" not found in " +
                                "\"{1}\" or directory not readable.")
                               .format(jube2.conf.CONFIGURATION_FILENAME,
                                       benchmark_folder))
            if benchmark_folder not in found_benchmarks:
                found_benchmarks.append(benchmark_folder)
    else:
        if (args.id is not None) and ("all" in args.id):
            # Add all available benchmark folder
            found_benchmarks = all_benchmarks
        else:
            # Get highest benchmark id and build benchmark_folder
            benchmark_id = jube2.util.util.get_current_id(args.dir)
            benchmark_folder = jube2.util.util.id_dir(args.dir, benchmark_id)
            if os.path.isdir(benchmark_folder):
                found_benchmarks.append(benchmark_folder)
            else:
                raise OSError("No benchmark directory found in \"{0}\""
                              .format(args.dir))

    found_benchmarks = \
        [benchmark_folder for benchmark_folder in found_benchmarks if
         os.path.isfile(os.path.join(benchmark_folder,
                                     jube2.conf.CONFIGURATION_FILENAME))]

    found_benchmarks.sort()
    return found_benchmarks

def search_for_workpackage(args, search_for_step=False):
    """Search for existing workpackages"""
    found_benchmarks = search_for_benchmarks(args)
    found_workpackages = list()
    for benchmark_folder in found_benchmarks:
        benchmark = \
            _load_existing_benchmark(args, benchmark_folder,
                                     load_analyse=False)
        if benchmark is not None:
            if args.workpackage:
                for wp_id in args.workpackage:
                    if search_for_step and args.step:
                        LOGGER.warning("The '-s' option is ignored if "
                                       "workpackages are selected by their ID "
                                       "using '-w'.")
                    if benchmark.workpackage_by_id(int(wp_id)) is None:
                        raise RuntimeError(("Workpackage ID \"{0}\" not " +
                                            "found in benchmark \"{1}\".")
                                           .format(wp_id, benchmark.id))
                    else:
                        found_workpackages.append(
                            benchmark.workpackage_by_id(int(wp_id)))
            elif search_for_step and args.step:
                for step_name in args.step:
                    if step_name not in benchmark.workpackages:
                        LOGGER.warning("Step \"{0}\" not found in benchmark "
                                     "\"{1}\".".format(step_name,
                                                       benchmark.name))
                    else:
                        for wp in benchmark.workpackages[step_name]:
                            found_workpackages.append(wp)
            elif search_for_step:
                for wp_name in benchmark.workpackages:
                    for wp in benchmark.workpackages[wp_name]:
                        found_workpackages.append(wp)
    return found_workpackages

def run_new_benchmark(args):
    """Start a new benchmark run"""

    jube2.conf.HIDE_ANIMATIONS = args.hide_animation
    jube2.conf.EXIT_ON_ERROR = args.error

    id_cnt = 0

    # Extract tags
    tags = args.tag
    if tags is not None:
        tags = set(tags)

    for path in args.files:
        # Setup Logging
        jube2.log.change_logfile_name(
            filename=os.path.join(os.path.dirname(path),
                                  jube2.conf.DEFAULT_LOGFILE_NAME))

        # Add log information
        LOGGER.debug("Command: {0} {1}".format(
            os.path.basename(sys.argv[0]), " ".join(sys.argv[1:])))
        LOGGER.debug("Version: {0}".format(jube2.conf.JUBE_VERSION))

        # Read new benchmarks
        if args.include_path is not None:
            include_pathes = [include_path for include_path in
                              args.include_path if include_path != ""]
        else:
            include_pathes = None
        parser = jube2.jubeio.Parser(path, tags, include_pathes,
                                     args.force, args.strict)
        benchmarks, only_bench, not_bench = parser.benchmarks_from_xml()

        # Add new comment
        if args.comment is not None:
            for benchmark in benchmarks.values():
                benchmark.comment = re.sub(r"\s+", " ", args.comment)

        # CLI input overwrite fileinput
        if args.only_bench:
            only_bench = args.only_bench
        if args.not_bench:
            not_bench = args.not_bench

        # No specific -> do all
        if len(only_bench) == 0 and benchmarks is not None:
            only_bench = list(benchmarks)

        for bench_name in only_bench:
            if bench_name in not_bench:
                continue
            bench = benchmarks[bench_name]
            # Set user defined id
            if (args.id is not None) and (len(args.id) > id_cnt):
                if args.id[id_cnt] < 0:
                    LOGGER.warning("Negative ids are not allowed. Skipping id "
                                   "'{}'.".format(args.id[id_cnt]))
                    id_cnt += 1
                    continue
                bench.id = args.id[id_cnt]
                id_cnt += 1
            # Change runtime outpath if specified
            if args.outpath is not None:
                bench.outpath = args.outpath
            # Start benchmark run
            bench.new_run()
            # Run analyse
            if args.analyse or args.result:
                jube2.log.change_logfile_name(os.path.join(
                    bench.bench_dir, jube2.conf.LOGFILE_ANALYSE_NAME))
                bench.analyse()

            # Create result data
            if args.result:
                jube2.log.change_logfile_name(os.path.join(
                    bench.bench_dir, jube2.conf.LOGFILE_RESULT_NAME))
                bench.create_result(show=True)

            # Clean up when using debug mode
            if jube2.conf.DEBUG_MODE:
                bench.delete_bench_dir()

        # Reset logging
        jube2.log.only_console_log()


def _continue_benchmark(benchmark_folder, args):
    """Continue existing benchmark"""

    jube2.conf.EXIT_ON_ERROR = args.error

    benchmark = _load_existing_benchmark(args, benchmark_folder)

    if benchmark is None:
        return

    # Change logfile
    jube2.log.change_logfile_name(os.path.join(
        benchmark_folder, jube2.conf.LOGFILE_CONTINUE_NAME))

    # Run existing benchmark
    benchmark.run()

    # Run analyse
    if args.analyse or args.result:
        jube2.log.change_logfile_name(os.path.join(
            benchmark_folder, jube2.conf.LOGFILE_ANALYSE_NAME))
        benchmark.analyse()

    # Create result data
    if args.result:
        jube2.log.change_logfile_name(os.path.join(
            benchmark_folder, jube2.conf.LOGFILE_RESULT_NAME))
        benchmark.create_result(show=True)

    # Clean up when using debug mode
    if jube2.conf.DEBUG_MODE:
        benchmark.reset_all_workpackages()

    # Reset logging
    jube2.log.only_console_log()


def _analyse_benchmark(benchmark_folder, args):
    """Analyse existing benchmark"""
    benchmark = _load_existing_benchmark(args, benchmark_folder,
                                         load_analyse=False)
    if benchmark is None:
        return

    # Update benchmark data
    _update_analyse_and_result(args, benchmark)

    # Change logfile
    jube2.log.change_logfile_name(os.path.join(
        benchmark_folder, jube2.conf.LOGFILE_ANALYSE_NAME))

    LOGGER.info(jube2.util.output.text_boxed(
        ("Analyse benchmark \"{0}\" id: {1}").format(benchmark.name,
                                                     benchmark.id)))
    benchmark.analyse()
    if os.path.isfile(
            os.path.join(benchmark_folder, jube2.conf.ANALYSE_FILENAME)):
        LOGGER.info(">>> Analyse data storage: {0}".format(os.path.join(
            benchmark_folder, jube2.conf.ANALYSE_FILENAME)))
    else:
        LOGGER.info(">>> Analyse data storage \"{0}\" not created!".format(
            os.path.join(benchmark_folder, jube2.conf.ANALYSE_FILENAME)))
    LOGGER.info(jube2.util.output.text_line())

    # Reset logging
    jube2.log.only_console_log()


def _benchmark_result(benchmark_folder, args, result_list=None):
    """Show benchmark result"""
    benchmark = _load_existing_benchmark(args, benchmark_folder)
    if result_list is None:
        result_list = list()

    if benchmark is None:
        return result_list

    if (args.update is None) and (args.tag is not None) and \
            (len(benchmark.tags & set(args.tag)) == 0):
        return result_list

    # Update benchmark data
    _update_analyse_and_result(args, benchmark)

    # Run benchmark analyse
    if args.analyse:
        jube2.log.change_logfile_name(os.path.join(
            benchmark_folder, jube2.conf.LOGFILE_ANALYSE_NAME))
        benchmark.analyse(show_info=False)

        # Change logfile
    jube2.log.change_logfile_name(os.path.join(
        benchmark_folder, jube2.conf.LOGFILE_RESULT_NAME))

    # Create benchmark results
    result_list = benchmark.create_result(only=args.only,
                                          data_list=result_list,
                                          style=args.style,
                                          select=args.select,
                                          exclude=args.exclude)

    # Reset logging
    jube2.log.only_console_log()

    return result_list


def _update_analyse_and_result(args, benchmark):
    """Update analyse and result data in given benchmark by using the
    given update file"""
    if args.update is not None:
        dirname = os.path.dirname(args.update)
        # Extract tags
        benchmark.add_tags(args.tag)
        tags = benchmark.tags

        # Read new benchmarks
        if args.include_path is not None:
            include_pathes = [include_path for include_path in
                              args.include_path if include_path != ""]
        else:
            include_pathes = None
        parser = jube2.jubeio.Parser(args.update, tags, include_pathes,
                                     args.force, args.strict)
        benchmarks = parser.benchmarks_from_xml()[0]

        # Update benchmark
        for bench in benchmarks.values():
            if bench.name == benchmark.name:
                benchmark.update_analyse_and_result(bench.patternsets,
                                                    bench.analyser,
                                                    bench.results,
                                                    bench.results_order,
                                                    dirname)
                break
        else:
            LOGGER.debug(("No benchmark data for benchmark {0} was found " +
                          "while running update.").format(benchmark.name))


def _remove_benchmark(benchmark_folder, args):
    """Remove existing benchmark"""
    remove = True
    if not args.force:
        try:
            inp = raw_input("Really remove \"{0}\" (y/n):"
                            .format(benchmark_folder))
        except NameError:
            inp = input("Really remove \"{0}\" (y/n):"
                        .format(benchmark_folder))
        remove = inp.startswith("y")
    if remove:
        # Delete benchmark folder
        shutil.rmtree(benchmark_folder, ignore_errors=True)


def _remove_workpackage(workpackage, args):
    """Remove existing workpackages"""
    remove = True
    # Ignore deleted/unstarted workpackages
    if workpackage.started:
        if not args.force:
            try:
                inp = raw_input(("Really remove \"{0}\" and its dependent " +
                                 "workpackages (y/n):")
                                .format(workpackage.workpackage_dir))
            except NameError:
                inp = input(("Really remove \"{0}\" and its dependent " +
                             "workpackages (y/n):")
                            .format(workpackage.workpackage_dir))
            remove = inp.startswith("y")
        if remove:
            workpackage.remove()
            workpackage.benchmark.write_workpackage_information(
                os.path.join(workpackage.benchmark.bench_dir,
                             jube2.conf.WORKPACKAGES_FILENAME))


def _manipulate_comment(benchmark_folder, args):
    """Change or append the comment in given benchmark."""
    benchmark = _load_existing_benchmark(args,
                                         benchmark_folder=benchmark_folder,
                                         restore_workpackages=False,
                                         load_analyse=False)
    if benchmark is None:
        return

    # Change benchmark comment
    if args.append:
        comment = benchmark.comment + args.comment
    else:
        comment = args.comment
    benchmark.comment = re.sub(r"\s+", " ", comment)
    benchmark.write_benchmark_configuration(
        os.path.join(benchmark_folder,
                     jube2.conf.CONFIGURATION_FILENAME), outpath="..")


def gen_parser_conf():
    """Generate dict with parser information"""
    config = (
        (("-V", "--version"),
         {"help": "show version",
          "action": "version",
          "version": "JUBE, version {0}".format(
              jube2.conf.JUBE_VERSION)}),
        (("-v", "--verbose"),
         {"help": "enable verbose console output (use -vv to " +
                  "show stdout during execution and -vvv to " +
                  "show log and stdout)",
          "action": "count",
          "default": 0}),
        (("--debug",),
         {"action": "store_true",
          "help": 'use debugging mode'}),
        (("--force",),
         {"action": "store_true",
          "help": 'skip version check'}),
        (("--strict",),
         {"action": "store_true",
          "help": 'force need for correct version'}),
        (("--devel",),
         {"action": "store_true",
          "help": 'show development related information'})
    )

    return config


def gen_subparser_conf():
    """Generate dict with subparser information"""
    subparser_configuration = dict()

    # run subparser
    subparser_configuration["run"] = {
        "help": "processes benchmark",
        "func": run_new_benchmark,
        "arguments": {
            ("files",):
                {"metavar": "FILE", "nargs": "+", "help": "input file"},
            ("--only-bench",):
                {"nargs": "+", "help": "only run benchmark"},
            ("--not-bench",):
                {"nargs": "+", "help": "do not run benchmark"},
            ("-t", "--tag"):
                {"nargs": "+", "help": "select tags"},
            ("-i", "--id"):
                {"type": int, "help": "use specific benchmark id",
                 "nargs": "+"},
            ("-e", "--error"):
                {"action": "store_true", "help": "exit on error"},
            ("--hide-animation",):
                {"action": "store_true", "help": "hide animations"},
            ("--include-path",):
                {"nargs": "+", "help": "directory containing include files"},
            ("-a", "--analyse"):
                {"action": "store_true", "help": "run analyse"},
            ("-r", "--result"):
                {"action": "store_true", "help": "show results"},
            ("-m", "--comment"):
                {"help": "add comment"},
            ("-o", "--outpath"):
                {"help": "overwrite outpath directory"}
        }
    }

    # continue subparser
    subparser_configuration["continue"] = {
        "help": "continue benchmark",
        "func": continue_benchmarks,
        "arguments": {
            ("dir",):
                {"metavar": "DIRECTORY", "nargs": "?",
                 "help": "benchmark directory", "default": "."},
            ("-i", "--id"):
                {"help": "use benchmarks given by id",
                 "nargs": "+"},
            ("--hide-animation",):
                {"action": "store_true", "help": "hide animations"},
            ("-e", "--error"):
                {"action": "store_true", "help": "exit on error"},
            ("-a", "--analyse"):
                {"action": "store_true", "help": "run analyse"},
            ("-r", "--result"):
                {"action": "store_true", "help": "show results"}
        }
    }

    # analyse subparser
    subparser_configuration["analyse"] = {
        "help": "analyse benchmark",
        "func": analyse_benchmarks,
        "arguments": {
            ("dir",):
                {"metavar": "DIRECTORY", "nargs": "?",
                 "help": "benchmark directory", "default": "."},
            ("-i", "--id"):
                {"help": "use benchmarks given by id",
                 "nargs": "+"},
            ("-u", "--update"):
                {"metavar": "UPDATE_FILE",
                 "help": "update analyse and result configuration"},
            ("--include-path",):
                {"nargs": "+", "help": "directory containing include files"},
            ("-t", "--tag"):
                {"nargs": "+", "help": "select tags"}
        }
    }

    # result subparser
    subparser_configuration["result"] = {
        "help": "show benchmark results",
        "func": benchmarks_results,
        "arguments": {
            ("dir",):
                {"metavar": "DIRECTORY", "nargs": "?",
                 "help": "benchmark directory", "default": "."},
            ("-i", "--id"):
                {"help": "use benchmarks given by id",
                 "nargs": "+"},
            ("-a", "--analyse"):
                {"action": "store_true",
                 "help": "run analyse before creating result"},
            ("-u", "--update"):
                {"metavar": "UPDATE_FILE",
                 "help": "update analyse and result configuration"},
            ("--include-path",):
                {"nargs": "+", "help": "directory containing include files"},
            ("-t", "--tag"):
                {"nargs": '+', "help": "select tags"},
            ("-o", "--only"):
                {"nargs": "+", "metavar": "RESULT_NAME",
                 "help": "only create results given by specific name"},
            ("-r", "--reverse"):
                {"help": "reverse benchmark output order",
                 "action": "store_true"},
            ("-n", "--num"):
                {"type": int, "help": "show only last N benchmarks"},
            ("-s", "--style"):
                {"help": "overwrites table style type",
                 "choices": ["pretty", "csv", "aligned"]},
            ("--select",):
                {"nargs": "+",
                 "help": "display only given columns from the result "
                 "(changes also the output to the result file)"},
            ("--exclude",):
                {"nargs": "+", "help": "excludes given columns from the result "
                 "(changes also the output to the result file)"}
        }
    }

    # info subparser
    subparser_configuration["info"] = {
        "help": "benchmark information",
        "func": info,
        "arguments": {
            ('dir',):
                {"metavar": "DIRECTORY", "nargs": "?",
                 "help": "benchmark directory", "default": "."},
            ("-i", "--id"):
                {"help": "use benchmarks given by id",
                 "nargs": "+"},
            ("-s", "--step"):
                {"help": "show information for given step", "nargs": "*"},
            ("-p", "--parametrization"):
                {"help": "display only parametrization of given step",
                 "action": "store_true"},
            ("-c", "--csv-parametrization"):
                {"help": "display only parametrization of given step " +
                 "using csv format", "nargs": "?", "default": False,
                 "metavar": "SEPARATOR"},
            ("-w", "--workpackage"):
                {"help": "show information for given workpackage id",
                 "nargs": "*"}
        }
    }

    # status subparser
    subparser_configuration["status"] = {
        "help": "show benchmark status",
        "func": status,
        "arguments": {
            ('dir',):
                {"metavar": "DIRECTORY", "nargs": "?",
                 "help": "benchmark directory", "default": "."},
            ("-i", "--id"):
                {"help": "use benchmarks given by id",
                 "nargs": "+"}
        }
    }
    
    #output subparser
    subparser_configuration["output"] = {
        "help": "show filename of output",
        "func": output,
        "arguments": {
            ('dir',):
                {"metavar": "DIRECTORY", "nargs": "?",
                 "help": "benchmark directory", "default": "."},
            ("-i", "--id"):
                {"help": "use benchmarks given by id",
                 "nargs": "+"},
            ("-s", "--step"):
                {"help": "show filenames for given step", "nargs": "+"},
            ("-w", "--workpackage"):
                {"help": "show filenames for given workpackages id",
                "nargs": "+"},
            ("-d", "--display"):
                {"help": "display content of output file" , "action": "store_true"},
            ("-o", "--only"):
                {"help": "show only stdour or stderr",
                 "choices": ["stdout", "stderr"]}
        }
    }

    # comment subparser
    subparser_configuration["comment"] = {
        "help": "comment handling",
        "func": manipulate_comments,
        "arguments": {
            ('comment',):
                {"help": "comment"},
            ('dir',):
                {"metavar": "DIRECTORY", "nargs": "?",
                 "help": "benchmark directory", "default": "."},
            ("-i", "--id"):
                {"help": "use benchmarks given by id",
                 "nargs": "+"},
            ("-a", "--append"):
                {"help": "append comment to existing one",
                 "action": 'store_true'}
        }
    }

    # remove subparser
    subparser_configuration["remove"] = {
        "help": "remove benchmark or workpackages",
        "func": remove_benchmarks,
        "arguments": {
            ('dir',):
                {"metavar": "DIRECTORY", "nargs": "?",
                 "help": "benchmark directory", "default": "."},
            ("-i", "--id"):
                {"help": "remove benchmarks given by id",
                 "nargs": "+"},
            ("-w", "--workpackage"):
                {"help": "specifc workpackage id to be removed",
                 "nargs": "+"},
            ("-f", "--force"):
                {"help": "force removing, never prompt",
                 "action": "store_true"}
        }
    }

    # update subparser
    subparser_configuration["update"] = {
        "help": "Check if a newer JUBE version is available",
        "func": update_check
    }

    # log subparser
    subparser_configuration["log"] = {
        "help": "show benchmark logs",
        "func": show_log,
        "arguments": {
            ('dir',):
                {"metavar": "DIRECTORY", "nargs": "?",
                 "help": "benchmark directory", "default": "."},
            ('--command', "-c"):
                {"nargs": "+", "help": "show log for this command"},
            ("-i", "--id"):
                {"help": "use benchmarks given by id",
                 "nargs": "+"}
        }
    }

    # completion subparser
    subparser_configuration["complete"] = {
        "help": "generate shell completion ",
        "func": complete,
        "arguments": {
            ('--command-name', "-c"):
                {"nargs": 1,
                 "help": "name of command to be completed",
                 "default": [os.path.basename(sys.argv[0])]},
        }
    }

    return subparser_configuration


def _get_args_parser():
    """Create argument parser"""
    parser = argparse.ArgumentParser()

    for args, kwargs in gen_parser_conf():
        parser.add_argument(*args, **kwargs)

    subparsers = parser.add_subparsers(dest="subparser", help='subparsers')

    subparser_configuration = gen_subparser_conf()

    # create subparser out of subparser configuration
    subparser = dict()
    for name, subparser_config in subparser_configuration.items():
        subparser[name] = \
            subparsers.add_parser(
                name, help=subparser_config.get("help", ""),
                description=jube2.help.HELP.get(name, ""),
                formatter_class=argparse.RawDescriptionHelpFormatter)
        subparser[name].set_defaults(func=subparser_config["func"])
        if "arguments" in subparser_config:
            for names, arg in subparser_config["arguments"].items():
                subparser[name].add_argument(*names, **arg)

    # create help key word overview
    help_keys = sorted(list(jube2.help.HELP) + ["ALL"])
    max_word_length = max(map(len, help_keys)) + 4
    # calculate max number of keyword columns
    max_columns = jube2.conf.DEFAULT_WIDTH // max_word_length
    # fill keyword list to match number of columns
    help_keys += [""] * (len(help_keys) % max_columns)
    help_keys = list(zip(*[iter(help_keys)] * max_columns))
    # create overview
    help_overview = jube2.util.output.text_table(help_keys, separator="   ",
                                                 align_right=False)

    # help subparser
    subparser["help"] = \
        subparsers.add_parser(
            'help', help='command help',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description="available commands or info elements: \n" +
            help_overview)
    subparser["help"].add_argument('command', nargs='?',
                                   help="command or info element")
    subparser["help"].set_defaults(func=command_help)

    return parser, subparser


def main(command=None):
    """Parse the command line and run the requested command."""

    jube2.help.load_help()
    parser = _get_args_parser()[0]
    if command is None:
        args = parser.parse_args()
    else:
        args = parser.parse_args(command)

    jube2.conf.DEBUG_MODE = args.debug
    jube2.conf.VERBOSE_LEVEL = args.verbose

    if jube2.conf.VERBOSE_LEVEL > 0:
        args.hide_animation = True

    # Set new umask if JUBE_GROUP_NAME is used
    current_mask = os.umask(0)
    if (jube2.util.util.check_and_get_group_id() is not None) and \
            (current_mask > 2):
        current_mask = 2
    os.umask(current_mask)

    if args.subparser:
        jube2.log.setup_logging(mode="console",
                                verbose=(jube2.conf.VERBOSE_LEVEL == 1) or
                                        (jube2.conf.VERBOSE_LEVEL == 3))
        if args.devel:
            args.func(args)
        else:
            try:
                args.func(args)
            except Exception as exeption:
                # Catch all possible Exceptions
                LOGGER.error("\n" + str(exeption))
                jube2.log.reset_logging()
                exit(1)
    else:
        parser.print_usage()
    jube2.log.reset_logging()


if __name__ == "__main__":
    main()
