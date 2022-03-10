#!/usr/bin/env python
"""
A command line tool for using and manipulating SeisFlows3.
The main entry point to the SeisFlows3 package, this command line tool
facilitates interface with the underlying SeisFlows3 package.

.. rubric::
    $ seisflows -h  # runs the help command to investigate package features

.. note::
    To add new functions to the seisflows command line tool, you must:
    - Write a new function within the SeisFlows class
    - Add a new subparser with optional arguments to sfparser()
    - Add subparser to subparser dict at the end of sfparser()
"""
import os
import sys
import inspect
import logging
import warnings
import argparse
import subprocess
from glob import glob
from textwrap import wrap
from IPython import embed

from seisflows3 import logger
from seisflows3.tools import unix, tools, msg
from seisflows3.tools.tools import loadyaml, loadpy
from seisflows3.config import (init_seisflows, format_paths, Dict, custom_import,
                               NAMES, PACKAGES, ROOT_DIR)


def sfparser():
    """
    An command-line argument parser which allows for intuitive exploration of
    the available functions.

    Gets User defined arguments or assign defaults. Makes use of subparsers to
    get individual help statements for each of the main functions.

    .. rubric::
        $ seisflows {main arg} {optional sub arg}

    :rtype: argparse.ArgumentParser()
    :return: User defined or default arguments
    """
    class SubcommandHelpFormatter(argparse.RawDescriptionHelpFormatter):
        """
        Override the help statement to NOT print out available subcommands for a
        cleaner UI when calling this CLI tool.

        https://stackoverflow.com/questions/13423540/
                              argparse-subparser-hide-metavar-in-command-listing
        """
        def _format_action(self, action):
            parts = super()._format_action(action)
            if action.nargs == argparse.PARSER:
                parts = "\n".join(parts.split("\n")[1:])
            return parts

    # Initiate the argument parser with a nicely formatted ASCII descriptor
    parser = argparse.ArgumentParser(
        formatter_class=SubcommandHelpFormatter,
        description=f"{'='*80}\n\n"
                    f"{'SeisFlows3: Waveform Inversion Package':^80}\n\n"
                    f"{'='*80}",
        epilog="'seisflows [command] -h' for more detailed descriptions "
               "of each command.",
    )

    # Optional parameters
    parser.add_argument("-w", "--workdir", nargs="?", default=os.getcwd(),
                        help="The SeisFlows working directory, default: cwd")
    parser.add_argument("-p", "--parameter_file", nargs="?",
                        default="parameters.yaml",
                        help="Parameters file, default: 'parameters.yaml'")
    parser.add_argument("--path_file", nargs="?", default="paths.py",
                        help="Legacy path file, default: 'paths.py'")

    # Initiate a sub parser to provide nested help functions and sub commands
    subparser = parser.add_subparsers(
        title="command",
        description="Available SeisFlows arguments and their intended usages",
        dest="command",
    )
    # The following subparsers constitute the available SeisFlows3 commands
    # and each refers to a function within the SeisFlows class.
    # =========================================================================
    setup = subparser.add_parser(
        "setup", help="Setup working directory from scratch",
        description="""In the specified working directory, copy template 
        parameter file containing only module choices, and symlink source code 
        for both the base and super repositories for easy edit access. If a 
        parameter file matching the provided name exists in the working 
        directory, a prompt will appear asking the user if they want to 
        overwrite."""
    )
    setup.add_argument("-s", "--symlink", action="store_true",
                       help="symlink source code into the working directory")
    setup.add_argument("-o", "--overwrite", action="store_true",
                       help="automatically overwrites existing parameter file")
    # =========================================================================
    configure = subparser.add_parser(
        "configure", help="Fill parameter file with defaults",
        description="""SeisFlows parameter files will vary depending on 
        chosen modules and their respective required parameters. This function 
        will dynamically traverse the source code and generate a template 
        parameter file based on module choices. The resulting file incldues 
        docstrings and type hints for each parameter. Optional parameters will 
        be set with default values and required parameters and paths will be 
        marked appropriately. Required parameters must be set before a workflow
        can be submitted."""
    )
    configure.add_argument("-r", "--relative_paths", action="store_true",
                           help="Set default paths relative to cwd")
    # =========================================================================
    init = subparser.add_parser(
        "init", help="Initiate working environment",
        description="""Establish a SeisFlows working environment but don't 
        submit the workflow to the system and do not perform variable  error 
        checking. Saves the initial state as pickle files to allow for active 
        environment inspection prior to running 'submit'. Useful for debugging, 
        development and code exploration."""
    )
    init.add_argument("-c", "--check", action="store_true",
                      help="Perform parameter and path checking to ensure that "
                           "user-defined parameters are accepatable")
    # =========================================================================
    submit = subparser.add_parser(
        "submit", help="Submit initial workflow to system",
        description="""The main SeisFlows execution command. Submit a SeisFlows 
        workflow to the chosen system, equal to executing 
        seisflows.workflow.main(). This function will create and fill the 
        working directory with required paths, perform path and parameter 
        error checking, and establish the active working environment before
        executing the workflow."""
    )
    submit.add_argument("-f", "--force", action="store_true",
                        help="Turn off the default parameter precheck")
    submit.add_argument("-s", "--stop_after", default=None, type=str,
                        help="Optional override of the 'STOP_AFTER' parameter")
    # =========================================================================
    resume = subparser.add_parser(
        "resume", help="Re-submit previous workflow to system",
        description="""Resume a previously submitted workflow. Used when 
        an active environment exists in the working directory, and must be 
        submitted to the system again."""
    )
    resume.add_argument("-f", "--force", action="store_true",
                        help="Turn off the default parameter precheck")
    resume.add_argument("-r", "--resume_from", default=None, type=str,
                        help="Optional override of the 'RESUME_FROM' parameter")
    resume.add_argument("-s", "--stop_after", default=None, type=str,
                        help="Optional override of the 'STOP_AFTER' parameter")
    # =========================================================================
    restart = subparser.add_parser(
        "restart", help="Remove current environment and submit new workflow",
        description="""Akin to running seisflows clean; seisflows submit. 
        Restarts the workflow by removing the current state and submitting a 
        fresh workflow."""
    )
    restart.add_argument("-f", "--force", action="store_true",
                         help="Skip the clean and submit precheck statements")
    # =========================================================================
    clean = subparser.add_parser(
        "clean", help="Remove active working environment",
        description="""Delete all SeisFlows related files in the working 
        directory, except for the parameter file."""
    )
    clean.add_argument("-f", "--force", action="store_true", 
                       help="Skip the warning check that precedes the clean "
                       "function")
    # =========================================================================
    par = subparser.add_parser(
        "par", help="View and edit parameter file",
        description="""Directly edit values in the parameter file by providing
        the parameter and corresponding value. If no value is provided, will 
        simply print out the current value of the given parameter. Works also
        with path names."""
    )
    par.add_argument("parameter", nargs="?", help="Parameter to edit or view, "
                     "(case independent).")
    par.add_argument("value", nargs="?", default=None,
                     help="Optional value to set parameter to. If not given, "
                     "will print out current parameter. If given, will replace "
                     "current parameter with new value. Set as 'null' "
                     "for NoneType and set '' for empty string")
    par.add_argument("-p", "--skip_print", action="store_true", default=False,
                     help="Skip the print statement which is typically "
                          "sent to stdout after changing parameters.")
    # =========================================================================
    sempar = subparser.add_parser(
        "sempar", help="View and edit SPECFEM parameter file",
        description="""Directly edit values in the SPECFEM parameter file by 
        providing the parameter and corresponding value. If no value is 
        provided, will simply print out the current value of the given 
        parameter. Works also with path names."""
    )
    sempar.add_argument("parameter", nargs="?", help="Parameter to edit or "
                        "view (case independent)")
    sempar.add_argument("value", nargs="?", default=None,
                     help="Optional value to set parameter to.")
    # =========================================================================
    check = subparser.add_parser(
        "check",  formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""
Check parameters, state, or values of an active environment

    model     check the min/max values of currently active models tracked by
              optimize. 'seisflows check model [name]' to check specific model.
    iter      Check current interation and step count of workflow
    src       List source names and respective internal indices
    isrc      Check source name for corresponding index
                """,
        help="Check state of an active environment")

    check.add_argument("choice", type=str,  nargs="?",
                       help="Parameter, state, or value to check")
    check.add_argument("args", type=str,  nargs="*",
                       help="Generic arguments passed to check functions")
    # =========================================================================
    print_ = subparser.add_parser(
        "print", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""
Print information related to an active environment

    modules    Print available module names for all available packages
    flow       Print out the workflow.main() flow arguments
                    """,
        help="Print information related to an active environment")

    print_.add_argument("choice", type=str, nargs="?",
                        help="Parameter, state, or value to check")
    print_.add_argument("args", type=str, nargs="*",
                        help="Generic arguments passed to check functions")
    # =========================================================================
    subparser.add_parser("convert", help="Convert model file format", )
    # =========================================================================
    subparser.add_parser("reset", help="Clean current and submit new workflow",
                         description="Equal to running seisflows clean; "
                                     "seisflows submit")
    # =========================================================================
    inspect = subparser.add_parser(
        "inspect", help="View inheritenace and ownership",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
Display the order of inheritance for one or all of the SeisFlows modules.
e.g. 'seisflows inspect solver'

  OR

Determine method ownership for a given function, listing the exact package and 
module that defined it. This functionality occurs if both 'name' and 'func' are 
provided as positional arguments.
e.g. 'seisflows inspect solver eval_func'
"""
    )
    inspect.add_argument("name", type=str,  nargs="?", default=None,
                         help="Optional name of SeisFlows module to inspect")
    inspect.add_argument("func", type=str,  nargs="?", default=None,
                         help="Optional method name to inspect ownership for")
    # =========================================================================
    subparser.add_parser(
        "debug", help="Start interactive debug environment",
        description="""Starts an IPython debugging environment and loads an
        active SeisFlows working state, as well as distributing the SeisFlows
        module namespace. Allows exploration of the active state, as well as
        manually control of the workflow. Useful for recovery from unexpected
        workflow crashes. State changes will not be saved automatically. Type
        'workflow.checkpoint()' in the debug environment to save any changes
        made during debugging.
        """)
    # =========================================================================
    edit = subparser.add_parser(
        "edit", help="Open source code file in text editor",
        description="""Directly edit source code files in your favorite 
        terminal text editor. Simply a shortcut to avoid having to root around
        in the repository. Any saved edits will directly affect the SeisFlows
        source code and any code errors may lead to failure of the package;
        e.g. 'seisflows edit solver base'"""
    )
    edit.add_argument("name", type=str,  nargs="?", default=None,
                      help="Name of module to search for source file in")
    edit.add_argument("module", type=str,  nargs="?", default=None,
                      help="Name of specific module file to open, extension "
                           "not required")
    edit.add_argument("-e", "--editor", type=str,  nargs="?", default=None,
                      help="Chosen text editor, defaults to $EDITOR env var")
    edit.add_argument("-d", "--dont_open", action="store_true",
                      help="Dont open the text editor, just list full pathname")
    # =========================================================================
    # Defines all arguments/functions that expect a sub-argument
    subparser_dict = {"check": check, "par": par, "inspect": inspect,
                      "edit": edit, "sempar": sempar, "clean": clean, 
                      "restart": restart, "print": print_}
    if parser.parse_args().command in subparser_dict:
        return parser, subparser_dict[parser.parse_args().command]
    else:
        return parser, None


class SeisFlows:
    """
    The main entry point to the SeisFlows3 package, to be interacted with
    through the command line. This class is responsible for:
        1) setting up or re-creating a SeisFlows3 working enviornment,
        2) (re-)submitting workflows to the system,
        3) inspecting, manipulating or viewing a live working environment via
            command line arguments.

    .. rubric::
        $ seisflows -h

    .. note::
        Almost every modules requires loading of other modules, i.e. to run
        any checks we must load the entire SeisFlows environment, which is slow
        but provides the most flexibility when accessing internal information
    """
    logger = logging.getLogger(__name__).getChild(__qualname__)

    def __init__(self):
        """
        Parse user-defined arguments and establish internal parameters used to
        control which functions execute and how. Instance must be called to
        execute internal functions
        """
        self._parser, self._subparser = sfparser()
        self._paths = None
        self._parameters = None
        self._args = self._parser.parse_args()

    def __call__(self, command=None, **kwargs):
        """
        When called, SeisFlows will execute one of its internal functions

        .. rubric::
            # From the command line
            $ seisflows {command} {optional subcommand}

            # From inside a Python environment
            > from seisflows3.scripts.seisflows import SeisFlows
            > sf = SeisFlows()
            > sf("{command}", {optional subcommand}={value})

            # Example
            $ seisflows par linesearch

        :type command: str
        :param command: If not None, allows controlling this class from inside
            a Python environment. If sub-commands are required, these are
            inserted using the kwargs.
            Usually not required unless writing tests or scripting SF3 in Python
        :type return_self: bool
        :param return_self: if True, do not execute a command, which init
            usually does, but return the SeisFlows class itself. This is used
            just for testing purposes
        :return:
        """
        if command is not None:
            # This allows running SeisFlows() from inside a Python environment
            # mostly used for testing purposes but can also be used for scripts
            kwargs = {**kwargs, **vars(self._args)}  # include argparse defaults
            getattr(self, command)(**kwargs)
        else:
            # This is the main command-line functionality of the class
            # Print out the help statement if no command is given
            if len(sys.argv) == 1:
                self._parser.print_help()
                sys.exit(0)

            # Call the given function based on the user-defined name.
            # Throw in all arguments as kwargs and let the function sort it out
            getattr(self, self._args.command)(**vars(self._args))

    @property
    def _public_methods(self):
        """
        Return a list of all public methods within this class.

        .. warning::
            Only methods that can be called via the command line should be
            public, all other methods and attributes should be private.
        """
        return [_ for _ in dir(self) if not _.startswith("_")]

    def _register(self, force=True):
        """
        Load the paths and parameters from file into sys.modules, set the
        default parameters if they are missing from the file, and expand all
        paths to absolute pathnames.

        .. note::
            This is ideally the FIRST thing that happens everytime SeisFlows3
            is initiated. The package cannot do anything without the resulting
            PATH and PARAMETER variables.

        :type force: bool
        :param force: if False, print out a few key parameters and require
            user-input before allowing workflow to be submitted. This is
            usually run before submit and resume, to prevent job submission
            without user evaluation.
        """
        # Check if the filepaths exist
        if not os.path.exists(self._args.parameter_file):
            sys.exit(f"\n\tSeisFlows parameter file not found: "
                     f"{self._args.parameter_file}\n")

        # Register parameters from the parameter file
        if self._args.parameter_file.endswith(".yaml"):
            parameters = loadyaml(self._args.parameter_file)
            try:
                paths = parameters["PATHS"]
                parameters.pop("PATHS")
            except KeyError:
                paths = {}
        #  Allow for legacy .py parameter file naming
        elif self._args.parameter_file.endwith(".py"):
            warnings.warn(".py parameter and path files are deprecated in "
                          "favor of a .yaml parameter file. Please consider "
                          "switching as the use of legacy .py files may have "
                          "unintended consequences at runtime",
                          DeprecationWarning)

            if not os.path.exists(self._args.paths_file):
                sys.exit(f"\n\tLegacy parameter file requires corresponding "
                         f"path file\n")
            parameters = loadpy(self._args.parameter_file)
            paths = loadpy(self._args.path_file)
        else:
            raise TypeError(f"Unknown file format for "
                            f"{self._args.parameter_file}, file must be "
                            f"'.yaml' (preferred) or '.py' (legacy)")

        # WORKDIR needs to be set here as it's expected by most modules
        if "WORKDIR" not in paths:
            paths["WORKDIR"] = self._args.workdir

        # For submit() and resume(), provide a dialogue to stdout requiring a
        # visual pre-check of parameters before submitting workflow
        if not force and parameters["PRECHECK"]:
            print(msg.ParameterCheckStatement)
            for par in parameters["PRECHECK"]:
                par = par.upper()
                try:
                    print(f"\t{par}: {parameters[par]}")
                except KeyError:
                    print(f"\t{par}: !!! PARAMETER NOT FOUND !!!")
            print("\n")
            check = input("\tContinue? (y/[n]): ")
            if check != "y":
                sys.exit(-1)

        # Register parameters to sys, ensure they meet standards of the package
        sys.modules["seisflows_parameters"] = Dict(parameters)

        # Register paths to sys, expand to relative paths to absolute
        paths = format_paths(paths)
        sys.modules["seisflows_paths"] = Dict(paths)

        self._paths = paths
        self._parameters = parameters

    def _config_logging(self, level="DEBUG", filename="./output_log.txt", 
                        filemode="a", verbose=True):
        """
        Explicitely configure the logging module with some parameters defined
        by the user in the System module. 
        """
        PAR = sys.modules["seisflows_parameters"]
        PATH = sys.modules["seisflows_paths"]

        # Try to overload default parameters with user-defined. This will not
        # be possible if we haven't started the workflow yet.
        try:
            level = PAR.LOG_LEVEL
            verbose = PAR.VERBOSE
            filename = PATH.LOG
        except KeyError:
            pass

        # Two levels of verbosity on log level
        fmt_str_debug = ("%(asctime)s | %(levelname)-5s | "
                         "%(name)s.%(funcName)s()\n"
                         "> %(message)s")
        fmt_str_clean = "%(asctime)s | %(message)s"

        datefmt = "%Y-%m-%d %H:%M:%S"

        if verbose:
            fmt_str = fmt_str_debug
        else:
            fmt_str = fmt_str_clean

        formatter = logging.Formatter(fmt_str, datefmt=datefmt)

        # Instantiate logger during _register() as we now have user-defined pars
        logger.setLevel(level)

        # Stream handler to print log statements to stdout
        st_handler = logging.StreamHandler()
        st_handler.setFormatter(formatter)
        logger.addHandler(st_handler)

        # File handler to print log statements to text file
        file_handler = logging.FileHandler(filename, filemode)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    def _load_modules(self):
        """
        A function to load and check each of the SeisFlows modules,
        re-initiating the SeisFlows environment. All modules are reliant on one
        another so any access to SeisFlows requires loading everything
        simultaneously.
        """
        # Working directory should already have been created by submit()
        unix.cd(self._args.workdir)

        # Reload objects from Pickle files
        for NAME in NAMES:
            fullfile = os.path.join(self._args.workdir, "output",
                                    f"seisflows_{NAME}.p")

            if not os.path.exists(fullfile):
                sys.exit(f"\n\tNot a SeisFlows working directory, state file "
                         f"not found:\n\t{fullfile}\n")

            sys.modules[f"seisflows_{NAME}"] = tools.loadobj(fullfile)

        # Check parameters so that default values are present
        logger
        for NAME in NAMES:
            sys.modules[f"seisflows_{NAME}"].check()

    def setup(self, symlink=False, overwrite=False, **kwargs):
        """
        Initiate a SeisFlows working directory from scratch; establish a
        template parameter file and symlink the source code for easy access

        :type symlink: bool
        :param symlink: flag to turn on source code symlinking
        :type overwrite: bool
        :param overwrite: flag to force parameter file overwriting
        """
        PAR_FILE = os.path.join(ROOT_DIR, "templates", "parameters.yaml")
        REPO_DIR = os.path.abspath(os.path.join(ROOT_DIR, ".."))

        if os.path.exists(self._args.parameter_file):
            if not overwrite:
                print(f"\n\tParameter file '{self._args.parameter_file}' "
                      f"already exists\n")
                check = input(f"\tOverwrite with blank file? (y/[n]): ")
            else:
                check = "y"

            if check == "y":
                unix.rm(self._args.parameter_file)
        unix.cp(PAR_FILE, self._args.workdir)

        # Symlink the source code for easy access to repo
        if symlink:
            src_code = os.path.join(self._args.workdir, "source_code")
            if not os.path.exists(src_code):
                unix.mkdir(src_code)
                for package in PACKAGES:
                    unix.ln(os.path.join(REPO_DIR, package), src_code)

    def configure(self, **kwargs):
        """
        Dynamically generate the parameter file by writing out docstrings and
        default values for each of the SeisFlows3 module parameters.
        This function writes files manually, consistent with the .yaml format.
        """
        self._register(force=True)

        def write_header(f, paths_or_parameters, name=""):
            """Re-usable function to write docstring comments"""
            # Some aesthetically pleasing dividers to separate sections
            TOP = (f"\n# {'=' * 78}\n#\n"
                   f"# {name.upper():^78}\n# {'-' * len(name):^78}\n"
                   f"#\n")
            BOT = f"\n# {'=' * 78}\n"
            TAB = "    "  # 4spacegang

            f.write(TOP)
            for key, attrs in paths_or_parameters.items():
                if "type" in attrs:
                    f.write(f"# {key} ({attrs['type']}):\n")
                else:
                    f.write(f"# {key}:\n")
                # Ensure that total line width is no more than 80 characters
                docstrs = wrap(attrs["docstr"], width=77 - len(TAB),
                               break_long_words=False)
                for line, docstr in enumerate(docstrs):
                    f.write(f"#{TAB}{docstr}\n")
            f.write(BOT)

        def write_paths_parameters(f, paths_or_parameters, indent=""):
            """Re-usable function to write paths or parameters in yaml format"""
            TAB = "    "
            for key, attrs in paths_or_parameters.items():
                # Lists need to be treated differently in yaml format
                if isinstance(attrs["default"], list):
                    f.write(f"{key}:\n")
                    for val in attrs["default"]:
                        f.write(f"{TAB}- {val}\n")
                else:
                    # Yaml saves NoneType values as 'null' or blank lines
                    if attrs["default"] is None:
                        # f.write(f"{indent}{key}: null\n")
                        f.write(f"{indent}{key}:\n")
                    else:
                        f.write(f"{indent}{key}: {attrs['default']}\n")

        # Establish the paths and parameters provided by the user
        if not self._args.parameter_file.endswith(".yaml"):
            sys.exit(f"\n\tseisflows configure only applicable to .yaml "
                     f"parameter files\n")

        # Need to attempt importing all modules before we access any of them
        for NAME in NAMES:
            sys.modules[f"seisflows_{NAME}"] = custom_import(NAME)()

        # System defines foundational directory structure required by other
        # modules. Don't validate the parameters because they aren't yet set
        sys.modules["seisflows_system"].required.validate(paths=True,
                                                          parameters=False)

        # If writing to parameter file fails for any reason, the file will be
        # mangled, create a temporary copy that can be re-instated upon failure
        temp_par_file = f".{self._args.parameter_file}"
        unix.cp(self._args.parameter_file, temp_par_file)
        try:
            # Paths are collected for each but written at the end
            seisflows_paths = {}
            with open(self._args.parameter_file, "a") as f:
                for NAME in NAMES:
                    req = sys.modules[f"seisflows_{NAME}"].required
                    seisflows_paths.update(req.paths)
                    write_header(f, req.parameters, NAME)
                    write_paths_parameters(f, req.parameters)
                # Write the paths in the same format as parameters
                write_header(f, seisflows_paths, name="PATHS")
                f.write("PATHS:\n")
                if self._args.relative_paths:
                    # If requested, set the paths relative to the current dir
                    for key, attrs in seisflows_paths.items():
                        if attrs["default"] is not None:
                            seisflows_paths[key]["default"] = os.path.relpath(
                                                               attrs["default"])
                write_paths_parameters(f, seisflows_paths, indent="    ")
        except Exception as e:
            # General error catch as anything can happen here
            unix.rm(self._args.parameter_file)
            unix.cp(temp_par_file, self._args.parameter_file)
            sys.exit(f"\n\tseisflows configure failed with exception:\n\t{e}\n")
        else:
            unix.rm(temp_par_file)

    def init(self, **kwargs):
        """
        Establish a SeisFlows3 working environment without error checking.
        Save the initial state as pickle files for environment inspection.
        Useful for debugging, development and code exploration purposes.
        """
        self._register(force=True)

        unix.mkdir(self._args.workdir)
        unix.cd(self._args.workdir)

        init_seisflows()

        workflow = sys.modules["seisflows_workflow"]
        workflow.checkpoint()

        if self._args.check:
            for NAME in NAMES:
                sys.modules[f"seisflows_{NAME}"].required.validate()

    def submit(self, stop_after=None, force=False, **kwargs):
        """
        Main SeisFlows3 execution command. Submit the SeisFlows3 workflow to
        the chosen system, and execute seisflows.workflow.main(). Will create
        the working directory and any required paths and ensure that all
        required paths exist.

        :type stop_after: str
        :param stop_after: allow the function to overwrite the 'STOP_AFTER'
            parameter in the parameter file, which dictates how far the workflow
            will proceed until stopping. Must match flow function names in
            workflow.main()
        :type force: bool
        :param force: if True, turns off the parameter precheck and
            simply submits the workflow
        """
        # Ensure that the 'RESUME_FROM' parameter is not set, incase of restart
        self.par(parameter="resume_from", value="", skip_print=True)

        if stop_after is not None:
            self.par(parameter="STOP_AFTER", value=stop_after, skip_print=True)

        self._register(force=force)
        self._config_logging()

        # A list of paths that need to exist if provided by user
        REQ_PATHS = ["SPECFEM_BIN", "SPECFEM_DATA", "MODEL_INIT", "MODEL_TRUE",
                     "DATA", "LOCAL", "MASK"]

        # Check that all required paths exist before submitting workflow
        paths_dont_exist = []
        for key in REQ_PATHS:
            if key in self._paths:
                # If a required path is given (not None) and doesnt exist, exit
                if self._paths[key] and not os.path.exists(self._paths[key]):
                    paths_dont_exist.append(self._paths[key])
        if paths_dont_exist:
            print("\nThe following paths do not exist:\n")
            for path_ in paths_dont_exist:
                print(f"\t{path_}")
            print("\n")
            sys.exit()

        unix.mkdir(self._args.workdir)
        unix.cd(self._args.workdir)

        # Submit workflow.main() to the system
        init_seisflows()
        workflow = sys.modules["seisflows_workflow"]
        system = sys.modules["seisflows_system"]
        system.submit(workflow)

    def clean(self, force=False, **kwargs):
        """
        Clean the SeisFlows3 working directory except for the parameter file.

        :type force: bool
        :param force: ignore the warning check that precedes the clean() 
            function, useful if you don't want any input messages popping up
        """
        if force:
            check = "y"
        else:
            check = input("\n\tThis will remove all workflow objects, "
                          "\n\tleaving only the parameter file. "
                          "\n\tAre you sure you want to clean? "
                          "(y/[n]):\n")

        delete = ["logs", "output*", "stats", "scratch"]

        if check == "y":
            for fid in delete:
                for fid in glob(os.path.join(self._args.workdir, fid)):
                    # Safeguards against deleting files that should not be dltd
                    assert("parameters.yaml" not in fid)
                    assert(not os.path.islink(fid))

                    unix.rm(fid)

    def resume(self, stop_after=None, resume_from=None, force=False,
               **kwargs):
        """
        Resume a previously started workflow by loading the module pickle files
        and submitting the workflow from where it left off.
                :type stop_after: str
        :param stop_after: allow the function to overwrite the 'STOP_AFTER'
            parameter in the parameter file, which dictates how far the workflow
            will proceed until stopping. Must match flow function names in
            workflow.main()
        :type resume_from: str
        :param resume_from: allow the function to overwrite the 'RESUME_FROM'
            parameter in the parameter file, which dictates which function the
            workflow starts from, must match the flow functions given in
            workflow.main()
        :type force: bool
        :param force: if True, turns off the parameter precheck and
            simply submits the workflow
        """
        if stop_after is not None:
            self.par(parameter="STOP_AFTER", value=stop_after, skip_print=True)
        if resume_from is not None:
            self.par(parameter="RESUME_FROM", value=resume_from, skip_print=True)

        self._register(force=force)
        self._load_modules()
        self._config_logging()

        workflow = sys.modules["seisflows_workflow"]
        system = sys.modules["seisflows_system"]

        system.submit(workflow)

    def restart(self, force=False, **kwargs):
        """
        Restart simply means clean the workding dir and submit a new workflow.

        :type force: bool
        :param force: ignore the warning check that precedes the clean() 
            function, useful if you don't want any input messages popping up
        """
        self.clean(force=force)
        self.submit(force=force)

    def debug(self, **kwargs):
        """
        Initiate an IPython debugging environment to explore the currently
        active SeisFlows3 environment. Reloads the system modules in an
        interactive environment allowing exploration of the package space.
        Does not allow stepping through of code (not a breakpoint).
        """
        self._register(force=True)
        self._load_modules()
        self._config_logging()

        # Distribute modules to common names for easy access during debug mode
        PATH = sys.modules["seisflows_paths"]
        PAR = sys.modules["seisflows_parameters"]
        system = sys.modules["seisflows_system"]
        preprocess = sys.modules["seisflows_preprocess"]
        solver = sys.modules["seisflows_solver"]
        postprocess = sys.modules["seisflows_postprocess"]
        optimize = sys.modules["seisflows_optimize"]
        workflow = sys.modules["seisflows_workflow"]

        print("""
        ==================DEBUG MODE==================

        SeisFlows3's debug mode is an embedded IPython 
        environment. All modules are loaded by default. 
        Any changes made here will not be saved unless 
        you explicitely run 'workflow.checkpoint()'

        ==================DEBUG MODE==================
        \n"""
        )

        embed(colors="Neutral")

    def sempar(self, parameter, value=None, **kwargs):
        """
        check or set parameters in the SPECFEM parameter file.
        By default assumes the SPECFEM parameter file is called 'Par_file'
        But this can be overwritten by using the '-p' flag.

        usage

            seisflows sempar [parameter] [value]

            to check the parameter 'nproc' from the command line:

                seisflows sempar nstep

            to set the parameter 'model' to 'GLL':

                seisflows sempar model GLL

            to check the values of a velocity model (SPECFEM2D)

                seisflows sempar velocity_model

            to edit the values of a velocity model (SPECFEM2D)
                
                seisflows sempar velocity_model \
                    "1 1 2600.d0 5800.d0 3500.0d0 0 0 10.d0 10.d0 0 0 0 0 0 0\n"

        :type parameter: str
        :param parameter: parameter to check in parameter file. case insensitive
        :type value: str
        :param value: value to set for parameter. if none, will simply print out
            the current parameter value. to set as nonetype, set to 'null'
            SPECFEM2D: if set to 'velocity_model' allows the user to set and 
            edit the velocity model defined in the SPECMFE2D Par_file. Not a 
            very smart capability, likely easier to do this manually.
        """
        if parameter is None:
            self._subparser.print_help()
            sys.exit(0)

        # SPECFEM parameter file has both upper and lower case parameters,
        # force upper just for string checking
        parameter = parameter.upper()

        # !!! We are assuming here that the parameter file is called 'Par_file'
        if not os.path.exists(self._args.parameter_file):
            par_file = "Par_file"
        else:
            par_file = self._args.parameter_file

        with open(par_file, "r") as f:
            lines = f.readlines()

        # SPECIAL CASE: the internal mesher velocity model does not have a key
        # it is just simply a list of numbers. Allow the user to check and edit
        # this using a special keyword. The following constants assume that
        # the Par_file hasn't changed from version cf893667 (Nov. 29, 2021)
        MESHER_KEYWORD = "VELOCITY_MODEL"
        MESHER_INPUT_NUM = 15
        nbmodels = 1
        if parameter == MESHER_KEYWORD:
            for i, line in enumerate(lines):
                # Ignore commented lines, ignore other parameters 
                if "=" in line.strip() or "#" in line.strip():
                    continue

                # ASSUME: nbmodels comes before the velocity model AND number 
                # of velocity model lines is the same as nbmodels
                elif "nbmodels " in line:
                    key, val = line.strip().split()
                    nbmodels = int(val)  # replace the current val of 1
                else:
                    parts = line.strip().split()
                    if len(parts) == MESHER_INPUT_NUM:
                        MODEL = "".join(lines[i:i+nbmodels+1])
                        # At this point we have confirmed that we are looking at
                        # the velocity model
                        if value is None:
                            print(f"\n{MODEL}")
                        else:
                            print(f"\n{line}\n->")
                            lines[i] = f"{value}\n"
                            print(f"\n{value}")
                            with open(par_file, "w") as f:
                                f.writelines(lines)
                        break
            sys.exit(0)

        # STANDARD CASE: check or edit parameters in the Par_file
        # Determine the number of white spaces between key and delimiter to keep
        # formatting pretty 
        for line in lines:
            if "=" in line:
                parts = line.strip().split(" ")
                space = parts.count("")
                break

        # Parse through the lines and find the corresponding value
        for i, line in enumerate(lines):
            # check exact parameter name and ignore comment
            if f"{parameter:<{space}}" in line.upper() and line[0] != "#":
                if value is not None:
                    # these values still have string formatters attached
                    current_par, current_val = line.split("=")

                    # this retains the string formatters of the line
                    new_val = current_val.strip().replace(current_val.strip(), 
                                                          value)

                    lines[i] = f"{current_par:<{space}}= {new_val}\n"
                    print(f"\n\t{current_par.strip()} = "
                          f"{current_val.strip()} -> {value}\n")

                    with open(par_file, "w") as f:
                        f.writelines(lines)
                else:
                    print(f"\n\t{line}")
                break
        else:
            sys.exit(f"\n\t'{parameter}' not found in parameter file\n")

    def par(self, parameter, value=None, skip_print=False, **kwargs):
        """
        Check or set parameters in the seisflows3 parameter file.

        USAGE

            seisflows par [parameter] [value]

            to check the parameter 'NPROC' from the command line:

                seisflows par nproc

            to set the parameter 'BEGIN' to 2:

                seisflows par begin 2

            to change the scratch path to the current working directory:

                seisflows par scratch ./

        :type parameter: str
        :param parameter: parameter to check in parameter file. case insensitive
        :type value: str
        :param value: value to set for parameter. if None, will simply print out
            the current parameter value. to set as nonetype, set to 'null'
        :type skip_print: bool
        :param skip_print: skip the print statement which is typically sent
            to stdout after changing parameters.
        """
        if parameter is None:
            self._subparser.print_help()
            sys.exit(0)

        # SeisFlows3 parameter file dictates upper-case parameters
        parameter = parameter.upper()

        if not os.path.exists(self._args.parameter_file):
            sys.exit(f"\n\tparameter file '{self._args.parameter_file}' "
                     f"does not exist\n")

        if value is not None and value.lower() == "none":
            warnings.warn("to set values to nonetype, use 'null' not 'none'",
                         UserWarning)

        with open(self._args.parameter_file, "r") as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            # Check exact parameter name and ignore comment
            if f"{parameter}:" in line.strip()[:len(parameter) + 1] and \
                                                                 line[0] != "#":
                if value is not None:
                    # These values still have string formatters attached
                    current_par, current_val = line.split(":")

                    # this retains the string formatters of the line
                    new_val = current_val.strip().replace(current_val.strip(), 
                                                          value)
                    lines[i] = f"{current_par}: {new_val}\n"
                    # lines[i] = ": ".join([current_par, new_val])
                    if not skip_print:
                        print(f"\n\t{current_par.strip()}: "
                              f"{current_val.strip()} -> {value}\n")
                    with open(self._args.parameter_file, "w") as f:
                        f.writelines(lines)
                else:
                    if not skip_print:
                        print(f"\n\t{line}")
                break
        else:
            sys.exit(f"\n\t'{parameter}' not found in parameter file\n")

    def edit(self, name, module, editor=None, **kwargs):
        """
        Directly edit the SeisFlows3 source code matching the given name
        and module using the chosen text editor.

        USAGE

            seisflows edit [name] [module] [editor]

            To edit the base Solver class using vim, one would run:

                seisflows edit solver base vim

            To simply find the location of the inversion workflow source code:

                seisflows edit workflow inversion q

        :type name: str
        :param name: name of module, must match seisflows.config.NAMES
        :type module: str
        :param module: the module name contained under the SeisFlows3 namespace
        :type editor: str
        :param editor: optional chosen text editor to open the file.
            * If NoneType: defaults to system environment $EDITOR
            * If 'q': For quit, does not open an editor, simply prints fid
        """
        if name is None:
            self._subparser.print_help()
            sys.exit(0)

        editor = editor or os.environ.get("EDITOR")
        if editor is None:
            sys.exit("\n\t$EDITOR environment variable not set, set manually\n")

        REPO_DIR = os.path.abspath(os.path.join(ROOT_DIR, ".."))
        if name not in NAMES:
            sys.exit(f"\n\t{name} not in SeisFlows3 names: {NAMES}\n")

        for package in PACKAGES:
            fid_try = os.path.join(REPO_DIR, package, name, f"{module}.py")
            if os.path.exists(fid_try):
                if self._args.dont_open:
                    sys.exit(f"\n{fid_try}\n")
                else:
                    subprocess.call([editor, fid_try])
                    sys.exit(f"\n\tEdited file: {fid_try}\n")
        else:
            sys.exit(f"\n\tseisflows.{name}.{module} not found\n")

    def check(self, choice=None, **kwargs):
        """
        Check parameters, state or values  of an active SeisFlows3 environment.
        Type 'seisflows check --help' for a detailed help message.

        :type choice: str
        :param choice: underlying sub-function to choose
        """
        acceptable_args = {"model": self._check_model_parameters,
                           "iter": self._check_current_iteration,
                           "src": self._check_source_names,
                           "isrc": self._check_source_index}

        # Ensure that help message is thrown for empty commands
        if choice not in acceptable_args.keys():
            self._subparser.print_help()
            sys.exit(0)

        self._register(force=True)
        self._load_modules()
        acceptable_args[choice](*self._args.args, **kwargs)

    def print(self, choice=None, **kwargs):
        """
        Print information relating to an active SeisFlows3 environment.
        Type 'seisflows check --help' for a detailed help message.

        :type choice: str
        :param choice: underlying sub-function to choose
        """
        acceptable_args = {"modules": self._print_modules,
                           "flow": self._print_flow}

        # Ensure that help message is thrown for empty commands
        if choice not in acceptable_args.keys():
            self._subparser.print_help()
            sys.exit(0)

        acceptable_args[choice](*self._args.args, **kwargs)

    def reset(self, choice=None, **kwargs):
        """
        Mid-level function to wrap lower level reset functions
        """
        acceptable_args = {"line_search": self._reset_line_search,}

        # Ensure that help message is thrown for empty commands
        if choice not in acceptable_args.keys():
            self._subparser.print_help()
            sys.exit(0)

        self._register(force=True)
        self._load_modules()
        acceptable_args[choice](*self._args.args, **kwargs)

    def inspect(self, name=None, func=None, **kwargs):
        """
        Inspect inheritance hierarchy of classes, methods defined by SeisFlows.
        Useful when developing or debugging, facilitates identification of
        the package top-level.

        USAGE

            seisflows inspect [name] [method]

            To view overall hierarchy for all names in the SeisFlows3 namespace

                seisflows inspect

            To check the inheritance hierarchy of the 'workflow' module

                seisflows inspect workflow

            To check which class defined a given method, e.g. the 'eval_func'
            method attributed to the solver module

                seisflows inspect solver eval_func

        """
        self._register(force=True)
        self._load_modules()
        if func is None:
            self._inspect_module_hierarchy(name, **kwargs)
        else:
            self._inspect_class_that_defined_method(name, func, **kwargs)

    def convert(self, name, path=None, **kwargs):
        """
        Convert a model in the OUTPUT directory between vector to binary
        representation. Kwargs are passed through to solver.save()

        USAGE

            seisflows convert [name] [path] [**kwargs]

            To convert the vector model 'm_try' to binary representation in the
            output directory

                seisflows convert m_try

        :type name: str
        :param name: name of the model to convert, e.g. 'm_try'
        :type path: str
        :param path: path and file id to save the output model. if None, will
            default to saving in the output directory under the name of the
            model
        """
        self._load_modules(force=True)

        solver = sys.modules["seisflows_solver"]
        optimize = sys.modules["seisflows_optimize"]
        PATH = sys.modules["seisflows_paths"]

        if path is None:
            path = os.path.join(PATH.OUTPUT, name)
        if os.path.exists(path):
            sys.exit(f"\n\t{path} exists and this action would overwrite the "
                     f"existing path\n")

        solver.save(solver.split(optimize.load(name)), path=path, **kwargs )

    def validate(self, module=None, name=None):
        """
        Ensure that all the modules (and their respective subclasses) meet some
        necessary requirements such as having specific functions and parameters.
        Not a full replacement for running the test suite, but useful for
        checking newly written subclasses.

        USAGE

            To validate a specific subclass:

                seisflows validate workflow inversion

            To validate the entire codebase

                seisflows validate
        """
        raise NotImplementedError

    @staticmethod
    def _inspect_class_that_defined_method(name, func, **kwargs):
        """
        Given a function name and generalized module (e.g. solver), inspect
        which of the subclasses actually defined the function. Makes it easier
        to debug/edit source code as the user can quickly determine where
        in the source code they need to look to find the corresponding function.

        https://stackoverflow.com/questions/961048/get-class-that-defined-method

        :type name: str
        :param name: SeisFlows3 module name
        :type func: str
        :param func: Corresponding method/function name for the given module
        """
        # Dynamically get the correct module and function based on names
        try:
            module = sys.modules[f"seisflows_{name}"]
        except KeyError:
            sys.exit(f"\n\tSeisFlows3 has no module named '{name}'\n")
        try:
            method = getattr(module, func)
        except AttributeError:
            sys.exit(f"\n\tSeisFlows.{name} has no function '{func}'\n")

        method_name = method.__name__
        if method.__self__:
            classes = [method.__self__.__class__]
        else:
            # Deal with unbound method
            classes = [method.im_class]
        while classes:
            c = classes.pop()
            if method_name in c.__dict__:
                print(f"\n\t{c.__module__}.{c.__name__}.{func}\n")
                return
            else:
                classes = list(c.__bases__) + classes
        sys.exit(f"\n\tError matching class for SeisFlows.{name}.{func}\n")

    @staticmethod
    def _inspect_module_hierarchy(name=None, **kwargs):
        """
        Determine the order of class hierarchy for a given SeisFlows3 module.

        https://stackoverflow.com/questions/1401661/
                            list-all-base-classes-in-a-hierarchy-of-given-class

        :type name: str
        :param name: choice of module, if None, will print hierarchies for all
            modules.
        """
        for NAME in NAMES:
            if name and NAME != name:
                continue
            module = sys.modules[f"seisflows_{NAME}"]
            print(f"\n\t{NAME.upper()}", end=" ")
            for i, cls in enumerate(inspect.getmro(type(module))[::-1]):
                print(f"-> {cls.__name__}", end=" ")
        print("\n")

    def _reset_line_search(self, **kwargs):
        """
        Reset the machinery of the line search
        """
        optimize = sys.modules["seisflows_optimize"]
        workflow = sys.modules["seisflows_workflow"]
        
        current_step = optimize.line_search.step_count
        optimize.line_search.reset()
        new_step = optimize.line_search.step_count
    
        print(f"Step Count: {current_step} -> {new_step}")
        workflow.checkpoint()

    def _print_modules(self, name=None, package=None, **kwargs):
        """
        Print out available modules in the SeisFlows name space for all
        available packages and modules.

        :type name: str
        :param name: specify an specific module name to list
        :type package: str
        :param package: specify an indivdual package to search
        """
        module_list = return_modules()
        for name_, package_dict in module_list.items():
            if name is not None and name != name_:
                continue
            print(f"\n{name_.upper()}")
            for package_, module_list in package_dict.items():
                if package is not None and package_ != package:
                    continue
                print(f" * {package_}")
                for module_ in module_list:
                    print(f"\t{module_}")
        print("\n")

    def _print_flow(self, **kwargs):
        """
        Simply print out the seisflows3.workflow.main() flow variable which
        describes what order workflow functions will be run. Useful for
        filling out the RESUME_FROM and STOP_AFTER parameters.
        """
        self._register(force=True)
        self._load_modules()

        workflow = custom_import("workflow")()
        flow = workflow.main(return_flow=True)
        flow_str = "\n\t".join([f"{a+1}: {b.__name__}"
                                for a, b in enumerate(flow)]
                               )

        print(f"\n\tFLOW ARGUMENTS")
        print(f"\t{type(workflow)}\n")
        print(f"\t{flow_str}\n")

    def _check_model_parameters(self, src=None, **kwargs):
        """
        Print out the min/max values from one or all of the currently available
        models. Useful for checking what models are associated with what part of
        the workflow, e.g. evaluate function, evaluate gradient.

        :type src: str
        :param src: the name of a specific model to check, e.g. 'm_try', 
            otherwise will check parameters for all models
        """
        optimize = sys.modules["seisflows_optimize"]
        PATH = sys.modules["seisflows_paths"]

        avail = glob(os.path.join(PATH.OPTIMIZE, "m_*"))
        srcs = [os.path.basename(_) for _ in avail]
        if src:
            if src not in srcs:
                sys.exit(f"\n\t{src} not in available models {avail}\n")
            srcs = [src]
        for tag in srcs:
            m = optimize.load(tag)
            optimize.check_model_parameters(m, tag)

    def _check_current_iteration(self, **kwargs):
        """
        Display the current point in the workflow in terms of the iteration
        and step count number. Args are not used by allow for a more general
        check() function.
        """
        optimize = sys.modules["seisflows_optimize"]
        try:
            line = optimize.line_search
            cstr = (f"\n"
                    f"\tIteration:  {optimize.iter}\n"
                    f"\tStep Count: {line.step_count} / {line.step_count_max}\n"
                    )
            print(cstr)
        except AttributeError:
            sys.exit("\n\toptimization module has not been initialized yet\n")

    def _check_source_names(self, source_name=None, **kwargs):
        """
        Sources are tagged by name but also by index in the source names which
        can be confusing and usually requires doubling checking. This check
        just prints out source names next to their respective index, or if a
        source name is requested, provides the index for that

        :type source_name: str
        :param source_name: name of source to check index, if None will simply
            print out all sources
        """     
        solver = sys.modules["seisflows_solver"]

        if source_name:
            print(f"{solver.source_names.index(source_name)}: {source_name}")
        else:
            for i, source_name in enumerate(solver.source_names):
                print(f"{i:>3}: {source_name}")

    def _check_source_index(self, idx=None, **kwargs):
        """
        Look up source name by index

        :type idx: int
        :param idx: index of source to look up
        """     
        solver = sys.modules["seisflows_solver"]
        print(f"\n\t{idx}: {solver.source_names[int(idx)]}\n")


def return_modules():
    """
    Search for the names of available modules in SeisFlows name space.
    This simple function checks for files with a '.py' extension inside
    each of the sub-directories, ignoring private files like __init__.py.

    :rtype: dict of dict of lists
    :return: a dict with keys matching names and values as dicts for each
        package. nested list contains all the avaialble modules
    """
    REPO_DIR = os.path.abspath(os.path.join(ROOT_DIR, ".."))

    module_dict = {}
    for NAME in NAMES:
        module_dict[NAME] = {}
        for PACKAGE in PACKAGES:
            module_dict[NAME][PACKAGE] = []
            mod_dir = os.path.join(REPO_DIR, PACKAGE, NAME)
            for pyfile in sorted(glob(os.path.join(mod_dir, "*.py"))):
                stripped_pyfile = os.path.basename(pyfile)
                stripped_pyfile = os.path.splitext(stripped_pyfile)[0]
                if not stripped_pyfile.startswith("_"):
                    module_dict[NAME][PACKAGE].append(stripped_pyfile)

    return module_dict


def main():
    """
    Main entry point into the SeisFlows3 package is via the SeisFlows3 class
    """
    sf = SeisFlows()
    sf()


if __name__ == "__main__":
    main()
