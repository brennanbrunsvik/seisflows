#!/usr/bin/env python
"""
This is the subclass seisflows.solver.Specfem3D
This class provides utilities for the Seisflows solver interactions with
Specfem3D Cartesian. It inherits all attributes from seisflows.solver.Base,
and overwrites these functions to provide specified interaction with Specfem3D

Note: This subclass only works with the `su` (seismic unix) data format
"""
import os
from glob import glob

import sys
import warnings
import seisflows.plugins.solver.specfem3d as solvertools

from seisflows.tools import unix
from seisflows.tools.tools import exists
from seisflows.config import custom_import
from seisflows.tools.seismic import call_solver, getpar, setpar


# Seisflows configuration
PAR = sys.modules['seisflows_parameters']
PATH = sys.modules['seisflows_paths']

system = sys.modules['seisflows_system']
preprocess = sys.modules['seisflows_preprocess']


class Specfem3D(custom_import('solver', 'base')):
    """
    Python interface to Specfem3D Cartesian. This subclass inherits functions
    from seisflows.solver.Base

    !!! See base class for method descriptions !!!
    """
    def check(self):
        """
        Checks parameters and paths
        """
        # Run Base class checks
        super(Specfem3D, self).check()

        # Check time stepping parameters
        if "NT" not in PAR:
            raise Exception("'NT' not specified in parameters file")

        if "DT" not in PAR:
            raise Exception("'DT' not specified in parameters file")

        if "F0" not in PAR:
            raise Exception("'F0' not specified in praameters file")

        # Check data format for Specfem3D
        if "FORMAT" not in PAR:
            raise Exception("'FORMAT' not specified in parameters file")

        acceptable_formats = ["su", "SU"]
        if PAR.FORMAT not in acceptable_formats:
            raise Exception(f"'FORMAT' must be {acceptable_formats}")

    def generate_data(self, **model_kwargs):
        """
        Generates data using the True model, exports traces to `traces/obs`

        :param model_kwargs: keyword arguments to pass to `generate_mesh`
        """
        # Create the mesh
        self.generate_mesh(**model_kwargs)

        # Run the Forward simulation
        unix.cd(self.cwd)
        setpar('SIMULATION_TYPE', '1')
        setpar('SAVE_FORWARD', '.true.')
        call_solver(mpiexec=system.mpiexec(), executable='bin/xspecfem3D')

        # Move output waveforms into holding directory
        if PAR.FORMAT in ['SU', 'su']:
            unix.mv(src=glob(os.path.join("OUTPUT_FILES", "*_d?_SU")),
                    dst=os.path.join("traces", "obs"))

        # Export traces to disk for permanent storage
        if PAR.SAVETRACES:
            self.export_traces(os.path.join(PATH.OUTPUT, "traces", "obs"))

    def generate_mesh(self, model_path, model_name, model_type='gll'):
        """
        Performs meshing with internal mesher Meshfem3D and database generation

        :type model_path: str
        :param model_path: path to the model to be used for mesh generation
        :type model_name: str
        :param model_name: name of the model to be used as identification
        :type model_type: str
        :param model_type: available model types to be passed to the Specfem3D
            Par_file. See Specfem3D Par_file for available options.
        """
        available_model_types = ["gll"]

        self.initialize_solver_directories()
        unix.cd(self.cwd)

        # Run mesh generation
        assert(exists(model_path))
        if model_type in available_model_types:
            par = getpar("MODEL").strip()
            if par == "gll":
                self.check_mesh_properties(model_path)

                src = glob(os.path.join(model_path, "*"))
                dst = self.model_databases
                unix.cp(src, dst)

                call_solver(mpiexec=system.mpiexec(),
                            executable="bin/xmeshfem3D")
                call_solver(mpiexec=system.mpiexec(),
                            executable="bin/xgenerate_databases")

            # Export the model for future use in the workflow
            if self.taskid == 0:
                self.export_model(os.path.join(PATH.OUTPUT, model_name))
        else:
            raise NotImplementedError(f"MODEL={par} not implemented")

    def eval_func(self, *args, **kwargs):
        """
        Call eval_func from Base class
        """
        super(Specfem3d, self).eval_func(*args, **kwargs)

        # Work around SPECFEM3D conflicting name conventions
        self.rename_data()

    def forward(self, path='traces/syn'):
        """
        Calls SPECFEM3D forward solver, exports solver outputs to traces dir

        :type path: str
        :param path: path to export traces to after completion of simulation
        """
        # Set parameters and run forward simulation
        setpar('SIMULATION_TYPE', '1')
        setpar('SAVE_FORWARD', '.true.')
        call_solver(mpiexec=system.mpiexec(),
                    executable='bin/xgenerate_databases')
        call_solver(mpiexec=system.mpiexec(), executable='bin/xspecfem3D')

        # Find and move output traces
        if PAR.FORMAT in ['SU', 'su']:
            unix.mv(src=glob(os.path.join("OUTPUT_FILES", "*_d?_SU")), dst=path)

    def adjoint(self):
        """
        Calls SPECFEM3D adjoint solver, creates the `SEM` folder with adjoint
        traces which is required by the adjoint solver
        """
        setpar('SIMULATION_TYPE', '3')
        setpar('SAVE_FORWARD', '.false.')
        setpar('ATTENUATION ', '.false.')
        unix.rm('SEM')
        unix.ln('traces/adj', 'SEM')
        call_solver(mpiexec=system.mpiexec(), executable='bin/xspecfem3D')

    def check_solver_parameter_files(self):
        """
        Checks solver parameters 
        """
        nt = getpar(key="NSTEP", cast=int)
        dt = getpar(key="DT", cast=float)

        if nt != PAR.NT:
            if self.taskid == 0:
                warnings.warn("Specfem3D NSTEP != PAR.NT\n"
                              "overwriting Specfem3D with Seisflows parameter"
                              )
            setpar(key="NSTEP", val=PAR.NT)

        if dt != PAR.DT:
            if self.taskid == 0:
                warnings.warn("Specfem3D DT != PAR.DT\n"
                              "overwriting Specfem3D with Seisflows parameter"
                              )
            setpar(key="DT", val=PAR.DT)

        if self.mesh_properties.nproc != PAR.NPROC:
            if self.taskid == 0:
                warnings.warn("Specfem3D mesh nproc != PAR.NPROC")

        if 'MULTIPLES' in PAR:
            raise NotImplementedError

    def initialize_adjoint_traces(self):
        """
        Setup utility: Creates the "adjoint traces" expected by SPECFEM

        Note:
            Adjoint traces are initialized by writing zeros for all channels.
            Channels actually in use during an inversion or migration will be
            overwritten with nonzero values later on.
        """
        # Initialize adjoint traces as zeroes for all data_filenames
        # write to `traces/adj`
        super(Specfem3D, self).initialize_adjoint_traces()

        # Rename data to work around Specfem naming convetions
        self.rename_data()

        # Workaround for Specfem3D's requirement that all components exist,
        # even ones not in use as adjoint traces
        #
        # ??? Does this work properly? are you not copying actual data here?
        unix.cd(os.path.join(self.cwd, "traces", "adj"))
        for iproc in range(PAR.NPROC):
            for channel in ["x", "y", "z"]:
                src = f"{iproc:d}_d{PAR.CHANNELS[0]}_SU.adj"
                dst = f"{iproc:d}_d{channel}_SU.adj"
                if not exists(dst):
                    unix.cp(src, dst)

    def rename_data(self):
        """
        Works around conflicting data filename conventions

        Specfem3D's uses different name conventions for regular traces
        and 'adjoint' traces
        """
        if PAR.FORMAT in ['SU', 'su']:
            files = glob(os.path.join(self.cwd, "traces", "adj", "*SU"))
            unix.rename(old='_SU', new='_SU.adj', names=files)

    def write_parameters(self):
        """
        Write a set of parameters

        !!! This calls on plugins.solver.specfem3d.write_parameters()
            but that function doesn't exist !!!
        """
        unix.cd(self.cwd)
        solvertools.write_parameters(vars(PAR))

    def write_receivers(self):
        """
        Write a list of receivers into a text file

        !!! This calls on plugins.solver.specfem3d.write_receivers()
            but incorrect number of parameters is forwarded !!!
        """
        unix.cd(self.cwd)
        setpar(key="use_existing_STATIONS",
               val=".true.")

        _, h = preprocess.load("traces/obs")
        solvertools.write_receivers(h.nr, h.rx, h.rz)

    def write_sources(self):
        """
        Write sources to text file
        """
        unix.cd(self.cwd)
        _, h = preprocess.load(dir='traces/obs')
        solvertools.write_sources(PAR=vars(PAR), h=h)

    @property
    def data_wildcard(self):
        """
        Returns a wildcard identifier for channels

        !!! this only works for SU data?

        :rtype: str
        :return: wildcard identifier for channels
        """
        if PAR.FORMAT in ["SU", "su"]:
            channels = PAR.CHANNELS
            return "*_d[%s]_SU" % channels.lower()
        else:
            raise NotImplementedError

    @property
    def data_filenames(self):
        """
        Returns the filenames of all Data

        :rtype: list
        :return: list of data filenames
        """
        unix.cd(os.path.join(self.cwd, "traces", "obs"))

        if PAR.FORMAT in ["SU", "su"]:
            if not PAR.CHANNELS:
                return sorted(glob("*_d?_SU"))
            filenames = []
            for channel in PAR.CHANNELS:
                filenames += sorted(glob(f"*_d{channel}_SU"))
            return filenames
        else:
            raise NotImplementedError

    @property
    def kernel_databases(self):
        """
        The location of databases for kernel outputs
        """
        return os.path.join(self.cwd, "OUTPUT_FILES", "DATABASES_MPI")

    @property
    def model_databases(self):
        """
        The location of databases for model outputs
        """
        return os.path.join(self.cwd, "OUTPUT_FILES", "DATABASES_MPI")

    @property
    def source_prefix(self):
        """
        Specfem3D's preferred source prefix

        :rtype: str
        :return: source prefix
        """
        return "CMTSOLUTION"

