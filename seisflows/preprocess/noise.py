#!/usr/bin/env python3
"""
The SeisFlows Preprocessing module is in charge of interacting with seismic
data (observed and synthetic). It should contain functionality to read and write
seismic data, apply preprocessing such as filtering, quantify misfit,
and write adjoint sources that are expected by the solver.
"""
import os
import numpy as np
from concurrent.futures import ProcessPoolExecutor, wait
from glob import glob
from obspy.geodetics import gps2dist_azimuth

from seisflows.preprocess.default import Default
from seisflows.tools import unix
from seisflows.tools.config import get_task_id
from seisflows.tools.specfem import read_stations


class Noise(Default):
    """
    Noise Preprocess
    ----------------
    Ambient Noise Adjoint Tomography (ANAT) preprocessing functions built ontop
    of the default preprocessing module. Additional functionalities allow for
    rotating and weighting horizontal components (N + E and R + T).

    Parameters
    ----------

    Paths
    -----

    ***
    """
    def __init__(self, path_specfem_data, **kwargs):
        """
        Preprocessing module parameters

        .. note::
            Paths and parameters listed here are shared with other modules and 
            so are not included in the class docstring.

        :type path_specfem_data: str
        :param path_specfem_data: path to SPECFEM DATA/ directory which must
            contain the CMTSOLUTION, STATIONS and Par_file files used for
            running SPECFEM
        """
        super().__init__()

        self.path.specfem_data = path_specfem_data

        # Internally used paramaters that should be filled in by `setup`
        self._stations = None

    def setup(self):
        """
        Setup procedures required for preprocessing module
        """
        super().setup()

        # Station dictionary containing locations to use for rotation
        self._stations = read_stations(
            os.path.join(self.path.specfem_data, "STATIONS")
        )

    def check(self):
        """ 
        Checks parameters and paths
        """
        super().check()

        # This is a redundant check on the DATA/STATIONS file (solver also
        # runs this check). This is required by noise workflows to determine
        # station rotation
        assert(self.path.specfem_data is not None and
               os.path.exists(self.path.specfem_data)), (
            f"`path_specfem_data` must exist and must point to directory " 
            f"containing SPECFEM input files"
        )
        assert(os.path.exists(
            os.path.join(self.path.specfem_data, "STATIONS"))), (
            f"DATA/STATIONS does not exist but is required by preprocessing"
        )

        assert(self.syn_data_format.upper() == "ASCII"), \
            f"Noise preprocessing is only set up to work with 'ascii' " \
            f"sythetic format"

    def rotate_ne_traces_to_rt(self, source_name, data_wildcard,
                               kernels="RR,TT"):
        """
        Rotates N and E synthetics generated by N and E forward simulations to
        RR and TT component using the (back)azimuth between two stations.

        Necessary because the ANAT simulations are performed for N and E forces
        and components, but EGF data is usually given in R and T components to
        isolate Rayleigh and Love waves.

        :type source_name: str
        :param source_name: the name of the source to process
        :type data_wildcard: str
        :param data_wildcard: wildcard string that is used to find waveform
            data. Should match the `solver` module attribute, and have an
            empty string formatter that will be used to specify 'net', 'sta',
            and 'comp'. E.g., '{net}.{sta}.?X{comp}.sem.ascii'
        :type kernels: str
        :param kernels: comma-separated list of kernels to consider writing
            files for. Saves on file overhead by not writing files that are
            not required. Available are 'TT' and 'RR'. To do both, set as
            'RR,TT' (order insensitive)
        """
        # Get a list of synthetic waveform files to pass to parallelized fx.
        source_name = source_name or self._source_names[get_task_id()]
        syn_dir = os.path.join(self.path.solver, source_name, "traces", "syn")

        def return_trace_fids(force, component):
            """convenience return function to get filename based on two vals"""
            return sorted(glob(
                os.path.join(syn_dir, force, data_wildcard.format(component)))
            )

        # Define the list of file ids and paths required for rotation
        fids_nn = return_trace_fids("N", "N")
        fids_ne = return_trace_fids("N", "E")
        fids_en = return_trace_fids("E", "N")
        fids_ee = return_trace_fids("E", "E")

        # Create output directories for rotated waveforms
        for kernel in kernels.split(","):
            dir_ = os.path.join(syn_dir, kernel[0])  # T and/or R
            unix.mkdir(dir_)

        # Rotate NE streams to RT in parallel
        with ProcessPoolExecutor(max_workers=unix.nproc()) as executor:
            futures = [
                executor.submit(self._rotate_ne_trace_to_rt,
                                source_name, f_nn, f_ne, f_en, f_ee, kernels)
                for f_nn, f_ne, f_en, f_ee in zip(fids_nn, fids_ne,
                                                  fids_en, fids_ee)
                ]
        # Simply wait until this task is completed because they are file writing
        wait(futures)

    def _rotate_ne_trace_to_rt(self, source_name, f_nn, f_ne, f_en, f_ee,
                               kernels="RR,TT"):
        """
        Parallellizable function to rotate N and E trace to R and T based on
        a single source station and receiver station pair and their
        respective azimuth values

        .. warning::

            This function makes a lot of assumptions about the directory
            structure and the file naming scheme of synthetics. It is quite
            inflexible and any changes to how SeisFlows treats the solver
            directories or how SPECFEM creates synthetics may break it.

        .. note::

            We are assuming the structure of the filename is something
            like NN.SSS.CCc*, which is standard from SPECFEM

        :type source_name: str
        :param source_name: the name of the source to process
        :type f_nn: str
        :param f_nn: path to the NN synthetic waveform (N force, N component)
        :type f_ne: str
        :param f_ne: path to the NE synthetic waveform (N force, E component)
        :type f_en: str
        :param f_en: path to the EN synthetic waveform (E force, N component)
        :type f_nn: str
        :param f_nn: path to the NN synthetic waveform (N force, N component)
        :type kernels: str
        :param kernels: comma-separated list of kernels to consider writing
            files for. Available are 'TT' and 'RR'. To do both, set as
            'RR,TT' (order insensitive)
        """
        # Define pertinent information about files and output names
        net, sta, cha, *ext = os.path.basename(f_nn).split(".")
        ext = ".".join(ext)  # ['semd', 'ascii'] -> 'semd.ascii.'

        # Determine the source station's latitude and longitude value
        src_lat = self._stations[source_name].latitude
        src_lon = self._stations[source_name].longitude

        # Determine the receiver station's name and coordinates.
        # Assuming the structure of the file name here to get the net, sta code
        rcv_name = f"{net}_{sta}"
        rcv_lat = self._stations[rcv_name].latitude
        rcv_lon = self._stations[rcv_name].longitude

        # Calculate the azimuth (theta) and rotated back-azimuth (theta prime)
        # between the two stations. See Fig. 1 from Wang et al. (2019) equations
        _, az, baz = gps2dist_azimuth(lat1=src_lat, lon1=src_lon,
                                      lat2=rcv_lat, lon2=rcv_lon)
        # Theta != Theta' for a spherical Earth, but they will be close
        theta = np.deg2rad(az)
        theta_p = np.deg2rad((baz - 180) % 360)

        # Read in the N/E synthetic waveforms that need to be rotated
        # First letter represents the force direction, second is component
        # e.g., ne -> north force recorded on east component
        st_nn = self.read(f_nn, data_format=self.syn_data_format)
        st_ne = self.read(f_ne, data_format=self.syn_data_format)
        st_ee = self.read(f_ee, data_format=self.syn_data_format)
        st_en = self.read(f_en, data_format=self.syn_data_format)

        # We require four waveforms to rotate into the appropriate coord. sys.
        # See Wang et al. (2019) Eqs. 9 and 10 for the rotation matrix def.
        st_tt = st_nn.copy()
        st_rr = st_nn.copy()
        for tr_ee, tr_ne, tr_en, tr_nn, tr_tt, tr_rr in \
                zip(st_ee, st_ne, st_en, st_nn, st_tt, st_rr):
            # TT rotation from Wang et al. (2019) Eq. 9
            tr_tt.data = (+ 1 * np.cos(theta) * np.cos(theta_p) * tr_ee.data
                          - 1 * np.cos(theta) * np.sin(theta_p) * tr_ne.data
                          - 1 * np.sin(theta) * np.cos(theta_p) * tr_en.data
                          + 1 * np.sin(theta) * np.sin(theta_p) * tr_nn.data
                          )
            # RR rotation from Wang et al. (2019) Eq. 10
            tr_rr.data = (+ 1 * np.sin(theta) * np.sin(theta_p) * tr_ee.data
                          - 1 * np.sin(theta) * np.cos(theta_p) * tr_ne.data
                          - 1 * np.cos(theta) * np.sin(theta_p) * tr_en.data
                          + 1 * np.cos(theta) * np.cos(theta_p) * tr_nn.data
                          )

        if "TT" in kernels:
            # scratch/solver/{source_name}/traces/syn/T/NN.SSS.?XT.sem?*
            fid_t = os.path.join(self.path.solver, source_name, "traces", "syn",
                                 "T", f"{net}.{sta}.{cha[:2]}T.{ext}")
            self.write(st=st_tt, fid=fid_t)
        if "RR" in kernels:
            fid_r = os.path.join(self.path.solver, source_name, "traces", "syn",
                                 "R", f"{net}.{sta}.{cha[:2]}R.{ext}")
            self.write(st=st_rr, fid=fid_r)

