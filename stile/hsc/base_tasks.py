""" base_tasks.py
Contains the Task classes that interface between the LSST/HSC pipeline and the
systematics tests described by Stile.
"""

import os
import lsst.pex.config
import lsst.pipe.base
import lsst.meas.mosaic
from lsst.meas.mosaic.mosaicTask import MosaicTask
from lsst.pipe.tasks.dataIds import PerTractCcdDataIdContainer
from .sys_test_adapters import adapter_registry
import numpy

parser_description = """
This is a script to run Stile through the LSST/HSC pipeline.
You can configure which systematic tests to be run by setting the following option.
From command line, add
-c 'sys_tests.names=['TEST_NAME1', 'TEST_NAME2', ...]'
. You can also specipy this option by writing a file, e.g.,
====================== config.py ======================
import stile.lsst.base_tasks
root.sys_tests.names=['TEST_NAME1', 'TEST_NAME2', ...]
=======================================================
, and then adding an option 
-C config.py
to the command line. If you use a file, you can add and remove tests from a default
by the following option
root.sys_tests.names.add('TEST_NAME')'
root.sys_tests.names.remove('TEST_NAME')'
. 
"""

class SysTestData(object):
    """
    A simple container object holding the name of a sys_test, plus the corresponding masks and
    columns from the getMasks() and getRequiredColumns() methods of the sys_test.
    """
    def __init__(self):
        self.sys_test_name = None
        self.mask_list = None
        self.cols_list = None


class CCDSingleEpochStileConfig(lsst.pex.config.Config):
    # Set the default systematics tests for the CCD level.
    sys_tests = adapter_registry.makeField("tests to run", multi=True,
                    default=["StatsPSFFlux", #"GalaxyXGalaxyShear", "BrightStarShear",         
                             "StarXGalaxyShear", "StarXStarShear"])
    corr2_kwargs = lsst.pex.config.DictField(doc="extra kwargs to control corr2",
                        keytype=str, itemtype=str,
                        default={'ra_units': 'degrees', 'dec_units': 'degrees',
                                 'min_sep': '0.005', 'max_sep': '0.2',
                                 'sep_units': 'degrees', 'nbins': '20'})
    flags = lsst.pex.config.ListField(dtype=str, doc="Flags that indicate unrecoverable failures",
        default = ['flags.negative', 'deblend.nchild', 'deblend.too-many-peaks',
                   'deblend.parent-too-big', 'deblend.failed', 'deblend.skipped',
                   'deblend.has.stray.flux', 'flags.badcentroid', 'centroid.sdss.flags',
                   'centroid.naive.flags', 'flags.pixel.edge', 'flags.pixel.interpolated.any',
                   'flags.pixel.interpolated.center', 'flags.pixel.saturated.any',
                   'flags.pixel.saturated.center', 'flags.pixel.cr.any', 'flags.pixel.cr.center',
                   'flags.pixel.bad', 'flags.pixel.suspect.any', 'flags.pixel.suspect.center'])
    shape_flags = lsst.pex.config.ListField(dtype=str, 
        doc="Flags that indicate failures for shape measurements",
        default = ['shape.sdss.flags', 'shape.sdss.centroid.flags',
                   'shape.sdss.flags.unweightedbad', 'shape.sdss.flags.unweighted','shape.sdss.flags.shift', 'shape.sdss.flags.maxiter'])
    bright_star_sn_cutoff = 50

class CCDSingleEpochStileTask(lsst.pipe.base.CmdLineTask):
    """
    A basic Task class to run CCD-level single-epoch tests.  Inheriting from
    lsst.pipe.base.CmdLineTask lets us use the already-built command-line interface for the
    data ID, rather than reimplementing this ourselves.  Calling
    >>> CCDSingleEpochStileTask.parseAndRun()
    from within a script will send all the command-line arguments through the argument parser, then
    call the run() method sequentially, once per CCD defined by the input arguments.
    """
    # lsst magic
    ConfigClass = CCDSingleEpochStileConfig
    _DefaultName = "CCDSingleEpochStile"
    # necessary basic parameters for corr2 to run
    def __init__(self, **kwargs):
        lsst.pipe.base.CmdLineTask.__init__(self, **kwargs)
        self.sys_tests = self.config.sys_tests.apply()

    def run(self, dataRef):
        # Pull the source catalog from the butler corresponding to the particular CCD in the
        # dataRef.
        catalog = dataRef.get("src", immediate=True)

        # Hironao's dirty fix for getting a directory for saving results and plots
        # and a (visit, ccd) identifier for filename.
        # This part will be updated by Jim on branch "#20".
        # The directory is 
        # $SUPRIME_DATA_DIR/rerun/[rerun/name/for/stile]/%(pointing)05d/%(filter)s/stile_output.
        # The filename includes a (visit, ccd) identifier -%(visit)07d-%(ccd)03d.
        src_filename = (dataRef.get("src_filename", immediate=True)[0]).replace('_parent/','')
        dir = os.path.join(src_filename.split('output')[0],"stile_output")
        if os.path.exists(dir) == False:
            os.makedirs(dir)
        filename_chip = "-%07d-%03d" % (dataRef.dataId["visit"], dataRef.dataId["ccd"])

        # Remove objects so badly measured we shouldn't use them in any test.
        catalog = self.removeFlaggedObjects(catalog)
        sys_data_list = []
        extra_col_dict = {}
        # Now, pull the mask and required-quantity info from the individual systematics tests we're
        # going to run.  We'll generate any required quantities only for the data within the
        # corresponding mask; we'll also check for more specific flags, such as flux measurement
        # failures for tests where we need the flux or magnitude or color of an object, and
        # fold those into the overall mask.
        for sys_test in self.sys_tests:
            sys_test_data = SysTestData()
            sys_test_data.sys_test_name = sys_test.name
            # Masks expects: a tuple of masks, one for each required data set for the sys_test
            sys_test_data.mask_list = sys_test.getMasks(catalog, self.config)
            # cols expects: an iterable of iterables, describing for each required data set
            # the set of extra required columns. len(mask_list) should be equal to len(cols_list).
            sys_test_data.cols_list = sys_test.getRequiredColumns()
            # Generally, we will be updating the masks as we go to take care of the more granular
            # flags such as flux measurement errors.  However, the number of possible flags for
            # shape measurement is so large that checking for the flags each time was prohibitive
            # in terms of run time.  So we will grab the shape mask flags FIRST, for those masks
            # corresponding to data sets where we need shape quantities, and "and" those into the
            # base mask, rather than doing it every time we ask for a shape quantity.
            shape_masks = []
            for cols_list in sys_test_data.cols_list:
                if any([key in cols_list for key in
                                ['g1', 'g1_err', 'g2', 'g2_err', 'sigma', 'sigma_err']]):
                    shape_masks.append(self._computeShapeMask(catalog))
                else:
                    shape_masks.append(True)
            sys_test_data.mask_list = [numpy.logical_and(mask, shape_mask) 
                for mask, shape_mask in zip(sys_test_data.mask_list, shape_masks)]
            # Generate any quantities that aren't already in the source catalog, but can
            # be generated from things that *are* in the source catalog.
            for (mask, cols) in zip(sys_test_data.mask_list, sys_test_data.cols_list):
                self.generateColumns(dataRef, catalog, mask, cols, extra_col_dict)
            sys_data_list.append(sys_test_data)
        # Right now, we have a source catalog, plus a dict of other computed quantities.  Step
        # through the masks and required quantities and generate a NumPy array for each pair,
        # containing only the required quantities and only in the rows indicated by the mask.
        for sys_test, sys_test_data in zip(self.sys_tests, sys_data_list):
            new_catalogs = []
            for mask, cols in zip(sys_test_data.mask_list, sys_test_data.cols_list):
                new_catalog = {}
                for column in cols:
                    if column in extra_col_dict:
                        new_catalog[column] = extra_col_dict[column][mask]
                    elif column in catalog.schema:
                        try:
                            new_catalog[column] = catalog[column][mask]
                        except:
                            new_catalog[column] = (numpy.array([src[column]
                                                   for src in catalog])[mask])
                new_catalogs.append(self.makeArray(new_catalog))
            # run the test!
            if hasattr(sys_test.sys_test, 'getCF'):
                results = sys_test(self.config.corr2_kwargs, *new_catalogs)
            else:
                results = sys_test(*new_catalogs)
            # If there's anything fancy to do with plotting the results, do that.
            if hasattr(sys_test.sys_test, 'plot'):
                fig = sys_test.sys_test.plot(results)
                fig.savefig(os.path.join(dir, sys_test_data.sys_test_name+filename_chip+'.png'))
            if hasattr(results, 'savefig'):
                results.savefig(os.path.join(dir, sys_test_data.sys_test_name+filename_chip+'.png'))

    def removeFlaggedObjects(self, catalog):
        """
        Remove objects which have certain flags we consider unrecoverable failures for weak lensing.
        Currently set to be quite conservative--we may want to relax this in the future.

        @param catalog A source catalog pulled from the LSST pipeline.
        @returns       The source catalog, masked to the rows which don't have any of our defined
                       flags set.
        """
        masks = [catalog[flag]==False for flag in self.config.flags]
        mask = masks[0]
        for new_mask in masks[1:]:
            mask = numpy.logical_and(mask, new_mask)
        return catalog[mask]

    def makeArray(self, catalog_dict):
        """
        Take a dict whose keys contain NumPy arrays of the same length and turn it into a
        formatted NumPy array.
        """
        dtypes = []
        # Generate the dtypes.
        for key in catalog_dict:
            dtypes.append((key, catalog_dict[key].dtype))
        len_list = [len(catalog_dict[key]) for key in catalog_dict]
        if not len(set(len_list))==1:
            raise RuntimeError('Different catalog lengths for different columns!')
        # Make an empty array and fill it column by column.
        data = numpy.zeros(len_list[0], dtype=dtypes)
        for key in catalog_dict:
            data[key] = catalog_dict[key]
        return data

    def generateColumns(self, dataRef, catalog, mask, raw_cols, extra_col_dict):
        """
        Generate required columns which are not already in the data array,  and update
        `extra_col_dict` to include them.  Also update "mask" to exclude any objects which have
        specific failures for the requested quantities, such as flux measurement failures for
        flux/magnitude measurements.

        @param dataRef        A dataRef that is the source of the following data
        @param catalog        A source catalog from the LSST pipeline.
        @param mask           The mask indicating which rows to generate columns for.  `mask` is
                              updated by this function.
        @param cols           An iterable of strings indicating which quantities are needed.
        @param extra_col_dict A dict whose keys are quantity names and whose values are
                              NumPy arrays of those quantities.  "nan" is used to indicate
                              as-yet uncomputed results; elements which are something other than
                              "nan" are not recomputed.  `extra_col_dict` is updated by this
                              function.
        """
        cols = list(raw_cols) # so we can pop items and not mess up our column description elsewhere
        # The moments measurement is slow enough to make a difference if we're processing many
        # catalogs, so we do those first, and separately, all at once.  Here, we figure out if there
        # are any moments-related keys to pull out of the catalog.
        shape_keys = ['g1', 'g2', 'sigma']
        shape_err_keys = ['g1_err', 'g2_err', 'sigma_err', 'w']
        psf_shape_keys = ['psf_g1', 'psf_g2', 'psf_sigma']
        do_shape = [col for col in shape_keys if col in cols and not col in catalog.schema]
        do_err = [col for col in shape_err_keys if col in cols and not col in catalog.schema]
        do_psf = [col for col in psf_shape_keys if col in cols and not col in catalog.schema]
        shape_cols = do_shape+do_err+do_psf  # a list of all shape-related columns to process
        # Get calibration info.  "fcr_md" is the more granular calibration generated by the
        # coaddition routines, while "calexp" is the original calibrated image. The
        # datasetExists() call will fail if no tract is defined, hence the try-except block.
        try:
            if dataRef.datasetExists("fcr_md"):
                if shape_cols:
                    calib_data = dataRef.get("calexp")  # only used for WCS
                calib_metadata = dataRef.get("fcr_md")
                calib_type = "fcr"
            else:
                if shape_cols:
                    calib_data = dataRef.get("calexp")
                calib_metadata = dataRef.get("calexp_md")
                calib_type = "calexp"
        except:
            if shape_cols:
                calib_data = dataRef.get("calexp")
            calib_metadata = dataRef.get("calexp_md")
            calib_type = "calexp"

        if shape_cols:
            for col in shape_cols:
                cols.remove(col)
                # Make sure there's already a NumPy array in the dict associated with this key.
                # We use "nan" to mark the rows we haven't computed already.
                if col not in extra_col_dict:
                    extra_col_dict[col] = numpy.zeros(len(catalog))
                    extra_col_dict[col].fill('nan')
            # Now, figure out the rows where we need to compute at least one of these quantities
            nan_masks = [numpy.isnan(extra_col_dict[col]) for col in shape_cols]
            nan_mask = nan_masks[0]
            for nm in nan_masks[1:]:
                nan_mask = numpy.logical_or(nan_mask, nm)
            nan_and_col_mask = numpy.logical_and(nan_mask, mask)
            # We will have to transform to sky coordinates if the locations are in (ra,dec).  This
            # is the more common case, so we only use CCD coordinates if explicitly requested.
            if 'x' in cols or 'y' in cols:
                sky_coords = False
            else:
                sky_coords = True
            if any(nan_and_col_mask>0):
                # computeShapes returns a dict of ('key': column) pairs, and sometimes an extra
                # mask indicating where measurements were valid. Here, this is only used if
                # PSF shapes were computed, since we already computed the shape masking in run().
                shapes_dict, extra_mask = self.computeShapes(catalog[nan_and_col_mask], calib_data,
                    do_shape=do_shape, do_err=do_err, do_psf=do_psf, sky_coords=sky_coords)
                if extra_mask is not None:
                    mask[nan_and_col_mask] = numpy.logical_and(mask[nan_and_col_mask], extra_mask)
                for col in shape_cols:
                    extra_col_dict[col][nan_and_col_mask] = shapes_dict[col]
        # Now we do the other quantities.  A lot of this is similar to the above code.
        for col in cols:
            if not col in catalog.schema:
                if not col in extra_col_dict:
                    extra_col_dict[col] = numpy.zeros(len(catalog))
                    extra_col_dict[col].fill('nan')
                nan_mask = numpy.isnan(extra_col_dict[col])
                nan_and_col_mask = numpy.logical_and(nan_mask, mask)
                if any(nan_and_col_mask>0):
                    # "extra_mask" is the new mask with the quantity-specific flags
                    extra_col_dict[col][nan_and_col_mask], extra_mask = self.computeExtraColumn(
                        col, catalog[nan_and_col_mask], calib_metadata, calib_type)
                    if extra_mask is not None:
                        mask[nan_and_col_mask] = numpy.logical_and(mask[nan_and_col_mask],
                                                                   extra_mask)

    def _computeShapeMask(self, data):
        """
        Compute and return the mask for `data` that excludes pernicious shape measurement failures.
        """
        masks = [numpy.array([src.get(flag)==False for src in data]) 
                 for flag in self.config.shape_flags]
        mask = masks[0]
        for new_mask in masks[1:]:
            mask = numpy.logical_and(mask, new_mask)
        return mask

    def computeShapes(self, data, calib, do_shape=True, do_err=True, do_psf=True, sky_coords=True):
        """
        Compute the shapes for the given `data`, an LSST source catalog, with the associated
        `calib` calibrated exposure metadata ('calexp_md' or 'fcr_md', either works).

        @param data       An LSST source catalog whose shape moments you would like to retrieve.
        @param calib      The metadata from a calibrated exposure ('calexp_md' or 'fcr_md').  If
                          `sky_coords=False` (see below) this can be None.
        @param do_shape   A bool indicating whether to compute (g1,g2,sigma).
        @param do_err     A bool indicating whether to compute (g1_err,g2_err,sigma_err).
        @param do_psf     A bool indicating whether to compute (psf_g1,psf_g2,psf_sigma).
        @param sky_coords If True, compute the moments in ra, dec coordinates; else compute in
                          native coordinates (x,y for CCD).
        @returns          A tuple consisting of:
                              - A dict whose keys are column names ('g1', 'psf_sigma', etc) and
                                whose values are a NumPy array of those quantities
                              - None if no new mask was needed, or a NumPy array of bools indicating
                                which rows had valid measurements.
        """
        if sky_coords:
            wcs = calib.getWcs()
        # First pull the quantities from the catalog that we'll need.  This first version in the try
        # block is faster if it works, and the time cost if it fails is small, so we try it first...
        try:
            if sky_coords:
                localTransform = wcs.linearizePixelToSky(data.getCentroid())
                localLinearTranform = localTransform.getLinear()
            if do_shape or do_err:
                moments = data.get('shape.sdss')
                if sky_coords:
                    moments = moments.transform(localLinearTransform)
                ixx = moments.getIxx()
                ixy = moments.getIxy()
                iyy = moments.getIyy()
            # Get covariance of moments. We ignore off-diagonal components because
            # they are not implemented in the LSST pipeline yet.
            if do_err:
                covariances = data.get('shape.sdss.err')
                if sky_coords:
                    cov_ixx = numpy.zeros(covariances[:,0,0].shape)
                    cov_iyy = numpy.zeros(covariances[:,0,0].shape)
                    cov_ixy = numpy.zeros(covariances[:,0,0].shape)
                    # We need this loop because localLinearTransform is 1-d array of
                    # lsst.afw.geom.geomLib.LinearTransform so that we cannot specify
                    # an array of (i,j) component as localLinearTransform[:,i,j].
                    for i, (cov, lt) in enumerate(zip(covariances,localLinearTransform)):
                        cov_ixx[i] = (lt[0,0]**4*cov[0,0] +
                                      (2.*lt[0,0]*lt[0,1])**2*cov[2,2] + lt[0,1]**4*cov[1,1])
                        cov_iyy[i] = (lt[1,0]**4*cov[0,0] +
                                      (2.*lt[1,0]*lt[1,1])**2*cov[2,2] + lt[1,1]**4*cov[1,1])
                        cov_ixy[i] = ((lt[0,0]*lt[1,0])**2*cov[0,0] +
                                      (lt[0,0]*lt[1,1]+lt[0,1]*lt[1,0])**2*cov[2,2] + 
                                      (lt[0,1]*lt[1,1])**2*cov[1,1])
                else:
                    cov_ixx = covariances[:,0,0]
                    cov_iyy = covariances[:,1,1]
                    cov_ixy = covariances[:,2,2]
            if do_psf:
                psf_moments = data.get('shape.sdss.psf')
                if sky_coords:
                    psf_moments = psf_moments.transform(localLinearTransform)
                psf_ixx = psf_moments.getIxx()
                psf_iyy = psf_moments.getIyy()
                psf_ixy = psf_moments.getIxy()
        # ...but probably in most cases we'll have to iterate like this since the catalog is
        # already masked, which breaks the direct calls above.
        except:
            if sky_coords:
                localLinearTransform = [wcs.linearizePixelToSky(src.getCentroid()).getLinear()
                                    for src in data]
            if do_shape or do_err:
                moments = [src.get('shape.sdss') for src in data]
                if sky_coords:
                    moments = [moment.transform(lt) for moment, lt in
                                      zip(moments, localLinearTransform)]
                ixx = numpy.array([mom.getIxx() for mom in moments])
                ixy = numpy.array([mom.getIxy() for mom in moments])
                iyy = numpy.array([mom.getIyy() for mom in moments])
            if do_err:
                covariances = numpy.array([src.get('shape.sdss.err') for src in data])
                if sky_coords:
                    cov_ixx = numpy.zeros(covariances[:,0,0].shape)
                    cov_iyy = numpy.zeros(covariances[:,0,0].shape)
                    cov_ixy = numpy.zeros(covariances[:,0,0].shape)
                    for i, (cov, lt) in enumerate(zip(covariances,localLinearTransform)):
                        cov_ixx[i] = (lt[0,0]**4*cov[0,0] +
                                      (2.*lt[0,0]*lt[0,1])**2*cov[2,2] + lt[0,1]**4*cov[1,1])
                        cov_iyy[i] = (lt[1,0]**4*cov[0,0] +
                                      (2.*lt[1,0]*lt[1,1])**2*cov[2,2] + lt[1,1]**4*cov[1,1])
                        cov_ixy[i] = ((lt[0,0]*lt[1,0])**2*cov[0,0] +
                                      (lt[0,0]*lt[1,1]+lt[0,1]*lt[1,0])**2*cov[2,2] + 
                                      (lt[0,1]*lt[1,1])**2*cov[1,1])
                else:
                    cov_ixx = covariances[:,0,0]
                    cov_iyy = covariances[:,1,1]
                    cov_ixy = covariances[:,2,2]
            if do_psf:
                psf_moments = [src.get('shape.sdss.psf') for src in data]
                if sky_coords:
                    psf_moments = [moment.transform(lt) for moment, lt in
                                      zip(psf_moments, localLinearTransform)]
                psf_ixx = numpy.array([mom.getIxx() for mom in psf_moments])
                psf_ixy = numpy.array([mom.getIxy() for mom in psf_moments])
                psf_iyy = numpy.array([mom.getIyy() for mom in psf_moments])
        # Now, combine the moment measurements into the actual quantities we want.
        if do_shape:
            g1 = (ixx-iyy)/(ixx+iyy)
            g2 = 2.*ixy/(ixx+iyy)
            sigma = numpy.sqrt(0.5*(ixx+iyy))
        else:
            g1 = None
            g2 = None
            sigma = None
        if do_err:
            dg1_dixx = 2.*iyy/(ixx+iyy)**2
            dg1_diyy = -2.*ixx/(ixx+iyy)**2
            g1_err = numpy.sqrt(dg1_dixx**2 * cov_ixx + dg1_diyy**2 * cov_iyy)
            dg2_dixx = -2.*ixy/(ixx+iyy)**2
            dg2_diyy = -2.*ixy/(ixx+iyy)**2
            dg2_dixy = 2./(ixx+iyy)
            g2_err = numpy.sqrt(dg2_dixx**2 * cov_ixx + dg2_diyy**2 * cov_iyy +
                               2. * dg2_dixy**2 * cov_ixy)
            dsigma_dixx = 0.25/sigma
            dsigma_diyy = 0.25/sigma
            sigma_err = numpy.sqrt(dsigma_dixx**2 * cov_ixx + dsigma_diyy**2 * cov_iyy)
            w = numpy.maximum(g1_err,g2_err)
            w = 1./(0.36**2+w**2)
        else:
            g1_err = None
            g2_err = None
            sigma_err = None
            w = [1.]*len(data)
        if do_psf:
            psf_g1 = (psf_ixx-psf_iyy)/(psf_ixx+psf_iyy)
            psf_g2 = 2.*psf_ixy/(psf_ixx+psf_iyy)
            psf_sigma = numpy.sqrt(0.5*(psf_ixx+psf_iyy))
            extra_mask = numpy.array([src.get('flux.psf.flags')==0 &
                                 src.get('flux.psf.flags.psffactor')==0 for src in data])
        else:
            psf_g1 = None
            psf_g2 = None
            psf_sigma = None
            extra_mask = None
        return ({'g1': g1, 'g2': g2, 'sigma': sigma, 'g1_err': g1_err, 'g2_err': g2_err,
                 'sigma_err': sigma_err, 'psf_g1': psf_g1, 'psf_g2': psf_g2, 'psf_sigma': psf_sigma},
                 extra_mask)


    def computeExtraColumn(self, col, data, calib_data, calib_type):
        """
        Compute the quantity `col` for the given `data`.

        @param col        A string indicating the quantity needed.
        @param data       A (subset of a) source catalog from the LSST pipeline.
        @param calib_data Photometric calibration data for flux/magnitude measurements.
        @param calib_type Which type of calibration calib_data is ("fcr" or "calexp"--"fcr" for
                          coadds where available, else "calexp").
        @returns          A 2-element tuple.  The first element is a list or NumPy array of the
                          quantity indicated by `col`. The second is either None (if no further
                          masking is needed) or a NumPy array of boolean values indicating where the
                          quantity is reliable (True) or unusable in some way (False).

        """
        if col=="ra":
            return [src.getRa().asDegrees() for src in data], None
        elif col=="dec":
            return [src.getDec().asDegrees() for src in data], None
        elif col=="x":
            return [src.getX() for src in data], None
        elif col=="y":
            return [src.getY() for src in data], None
        elif col=="mag_err":
            return (2.5/numpy.log(10)*numpy.array([src.getPsfFluxErr()/src.getPsfFlux()
                                                    for src in data]),
                    numpy.array([src.get('flux.psf.flags')==0 &
                                 src.get('flux.psf.flags.psffactor')==0 for src in data]))
        elif col=="mag":
            # From Steve Bickerton's helpful HSC butler documentation
            if calib_type=="fcr":
                ffp = lsst.meas.mosaic.FluxFitParams(calib_data)
                x, y = data.getX(), data.getY()
                correction = numpy.array([ffp.eval(x[i], y[i]) for i in range(n)])
                zeropoint = 2.5*numpy.log10(fcr.get("FLUXMAG0")) + correction
            elif calib_type=="calexp":
                zeropoint = 2.5*numpy.log10(calib_data.get("FLUXMAG0"))
            return (zeropoint - 2.5*numpy.log10(data.getPsfFlux()),
                    numpy.array([src.get('flux.psf.flags')==0 &
                                 src.get('flux.psf.flags.psffactor')==0 for src in data]))
        elif col=="w":
            # Use uniform weights for now if we don't use shapes ("w" will be removed from the
            # list of columns if shapes are computed).
            return numpy.array([1.]*len(data)), None
        raise NotImplementedError("Cannot compute field %s" % col)

    @classmethod
    def _makeArgumentParser(cls):
        # This ContainerClass lets us use the tract-level photometric calibration rather than just
        # using the calibrated exposures (calexp).
        parser = lsst.pipe.base.ArgumentParser(name=cls._DefaultName)
        parser.add_id_argument("--id", "forced_src", help="data ID, with raw CCD keys + tract",
                               ContainerClass=PerTractCcdDataIdContainer)
        parser.description = parser_description
        return parser

    def writeConfig(self, *args, **kwargs):
        pass
    def writeSchema(self, *args, **kwargs):
        pass
    def writeMetadata(self, dataRef):
        pass

class CCDNoTractSingleEpochStileTask(CCDSingleEpochStileTask):
    """Like CCDSingleEpochStileTask, but we use a different argument parser that doesn't require
    an available coadd to run on the CCD level."""
    _DefaultName = "CCDNoTractSingleEpochStile"

    @classmethod
    def _makeArgumentParser(cls):
        parser = lsst.pipe.base.ArgumentParser(name=cls._DefaultName)
        parser.add_id_argument("--id", "src", help="data ID, with raw CCD keys")
        parser.description = parser_description
        return parser


class StileVisitRunner(CCDSingleEpochStileConfig):
    """Subclass of TaskRunner for Stile visit tasks.  Most of this code (incl this docstring)
    pulled from measMosaic.

    VisitSingleEpochStileTask.run() takes a number of arguments, one of which is a list of dataRefs
    extracted from the command line (whereas most CmdLineTasks' run methods take a single dataRef,
    and are called repeatedly).  This class transforms the processed arguments generated by the
    ArgumentParser into the arguments expected by VisitSingleEpochStileTask.run().  It will still
    call run() once per visit if multiple visits are present, but not once per CCD as would
    otherwise occur.

    See pipeBase.TaskRunner for more information.
    """

    @staticmethod
    def getTargetList(parsedCmd, **kwargs):
        # organize data IDs by visit
        refListDict = {}
        for ref in parsedCmd.id.refList:
            refListDict.setdefault(ref.dataId["visit"], []).append(ref)
        # we call run() once with each visit
        return [(visit,
                 refListDict[visit]
                 ) for visit in sorted(refListDict.keys())]

    def __call__(self, args):
        task = self.TaskClass(config=self.config, log=self.log)
        result = task.run(*args)

class VisitSingleEpochStileConfig(CCDSingleEpochStileConfig):
    # Set the default systematics tests for the visit level.  Some keys (eg "flags", "shape_flags")
    # inherited from CCDSingleEpochStileConfig.
    sys_tests = adapter_registry.makeField("tests to run", multi=True,
                    default=["StatsPSFFlux", #"GalaxyXGalaxyShear", "BrightStarShear",         
                             "StarXGalaxyShear", "StarXStarShear"])
    corr2_kwargs = lsst.pex.config.DictField(doc="extra kwargs to control corr2",
                        keytype=str, itemtype=str,
                        default={'ra_units': 'degrees', 'dec_units': 'degrees',
                                 'min_sep': '0.05', 'max_sep': '1',
                                 'sep_units': 'degrees', 'nbins': '20'})

class VisitSingleEpochStileTask(CCDSingleEpochStileTask):
    """
    A basic Task class to run visit-level single-epoch tests.  Inheriting from
    lsst.pipe.base.CmdLineTask lets us use the already-built command-line interface for the
    data ID, rather than reimplementing this ourselves.  Calling
    >>> VisitSingleEpochStileTask.parseAndRun()
    from within a script will send all the command-line arguments through the argument parser, then
    call the run() method sequentially, once per CCD defined by the input arguments.

    The "Visit" version of this class is different from the "CCD" level of the task in that we will
    have to combine catalogs from each CCD in the visit, and do some trickery with iterables to keep
    everything aligned.
    """
    # lsst magic
    RunnerClass = StileVisitRunner
    canMultiprocess = False
    ConfigClass = VisitSingleEpochStileConfig
    _DefaultName = "VisitSingleEpochStile"
    # necessary basic parameters for corr2 to run

    def run(self, visit, dataRefList):
        # It seems like it would make more sense to put all of this in a separate function and run
        # it once per catalog, then collate the results at the end (just before running the test).
        # Turns out that, compared to the current implementation, that takes 2-3 times as long to
        # run (!) even before you get to the collation step.  So, we duplicate some code here in
        # the name of runtime, at the expense of some complexity in terms of nested lists of things.
        # Some of this code is annotated more clearly in the CCD* version of this class.
        catalogs = [dataRef.get("src", immediate=True) for dataRef in dataRefList]
        catalogs = [self.removeFlaggedObjects(catalog) for catalog in catalogs]
        sys_data_list = []
        extra_col_dicts = [{} for catalog in catalogs]

        # Hironao's dirty fix for getting a directory for saving results and plots
        # and a (visit, chip) identifier for filename.
        # This part will be updated by Jim on branch "#20".
        # The directory is 
        # $SUPRIME_DATA_DIR/rerun/[rerun/name/for/stile]/%(pointing)05d/%(filter)s/stile_output.
        # The filename has a visit identifier -%(visit)07d-[ccds], where [ccds] is a reduced form
        # of a CCD list, e.g., if a CCD list is [0, 1, 2, 4, 5, 8, 10],
        # [ccds] becomes 0..2^4..5^8^10.
        src_filename = (dataRefList[0].get("src_filename", 
                                           immediate=True)[0]).replace('_parent/','')
        dir = os.path.join(src_filename.split('output')[0],"stile_output")
        if os.path.exists(dir) == False:
            os.makedirs(dir)
        ccds = [dataRef.dataId['ccd'] for dataRef in dataRefList]
        ccds.sort()
        ccd_str = "%s" % ccds[0]
        for i, ccd in enumerate(ccds[1:]):
            if not(ccd - 1 in ccds) and (ccd+1 in ccds):
                ccd_str += "^%s" % ccd
            elif (ccd - 1 in ccds) and not(ccd+1 in ccds):
                ccd_str += "..%s" % ccd
            elif not(ccd - 1 in ccds) and not(ccd+1 in ccds):
                ccd_str += "^%s" % ccd
        filename_chips = "-%07d-%s" % (dataRefList[0].dataId["visit"], ccd_str)

        # Some tests need to know which data came from which CCD
        for dataRef, catalog, extra_col_dict in zip(dataRefList, catalogs, extra_col_dicts):
            extra_col_dict['CCD'] = numpy.zeros(len(catalog), dtype=int)
            extra_col_dict['CCD'].fill(dataRef.dataId['ccd'])
        for sys_test in self.sys_tests:
            sys_test_data = SysTestData()
            sys_test_data.sys_test_name = sys_test.name
            # Masks expects: a tuple of masks, one for each required data set for the sys_test
            temp_mask_list = [sys_test.getMasks(catalog, self.config) for catalog in catalogs]
            # cols expects: an iterable of iterables, describing for each required data set
            # the set of extra required columns.
            sys_test_data.cols_list = sys_test.getRequiredColumns()
            shape_masks = []
            for cols_list in sys_test_data.cols_list:
                if any([key in sys_test_data.cols_list for key in ['g1', 'g1_err', 'g2', 'g2_err',
                                                                    'sigma', 'sigma_err']]):
                    shape_masks.append([self._computeShapeMask(catalog) for catalog in catalogs])
                else:
                    shape_masks.append([True]*len(catalogs))
            # Now, temp_mask_list is ordered such that there is one list per catalog, and the
            # list for each catalog iterates through the sys tests.  But shape_mask is ordered such
            # that there is one list per sys test, and the list for each sys test iterates through
            # the catalogs!  That's actually the form we want.  So this next line A) combines the
            # new shape masks with the old flag masks, and B) switches the nesting of the mask list
            # to be the ordering we expect.
            sys_test_data.mask_list = [[numpy.logical_and(mask[i], shape_mask)
                        for mask, shape_mask in zip(temp_mask_list, shape_masks[i])]
                        for i in range(len(temp_mask_list[0]))]
            for (mask_list, cols) in zip(sys_test_data.mask_list, sys_test_data.cols_list):
                for dataRef, mask, catalog, extra_col_dict in zip(dataRefList, mask_list, catalogs, extra_col_dicts):
                    self.generateColumns(dataRef, catalog, mask, cols, extra_col_dict)
            # Some tests need to know which data came from which CCD, so we add a column for that here
            # to make sure it's propagated through to the sys_tests.
            sys_test_data.cols_list = [tuple(list(cols)+['CCD']) for cols in sys_test_data.cols_list]
            sys_data_list.append(sys_test_data)
        for sys_test, sys_test_data in zip(self.sys_tests, sys_data_list):
            new_catalogs = []
            for mask_list, cols in zip(sys_test_data.mask_list, sys_test_data.cols_list):
                new_catalog = {}
                for column in cols:
                    for catalog, extra_col_dict, mask in zip(catalogs, extra_col_dicts, mask_list):
                        if column in extra_col_dict:
                            newcol = extra_col_dict[column][mask]
                        elif column in catalog.schema:
                            try:
                                newcol = catalog[column][mask]
                            except:
                                newcol = numpy.array([src[column] for src in catalog])[mask]
                        # The new_catalog dict has values which are lists of the quantity we want,
                        # one per dataRef.
                        if column in new_catalog:
                            new_catalog[column].append(newcol)
                        else:
                            new_catalog[column] = [newcol]
                new_catalogs.append(self.makeArray(new_catalog))
            if hasattr(sys_test.sys_test, 'getCF'):
                results = sys_test(self.config.corr2_kwargs, *new_catalogs)
            else:
                results = sys_test(*new_catalogs)
            fig = sys_test.sys_test.plot(results)
            fig.savefig(os.path.join(dir, sys_test_data.sys_test_name+filename_chips+'.png'))
            
    def makeArray(self, catalog_dict):
        """
        Take a dict whose keys contain lists of NumPy arrays which will concatenate to the same
        length and turn it into a single formatted NumPy array.
        """
        dtypes = []
        for key in catalog_dict:
            # It's possible (though unlikely...?) that the different catalogs will generate columns
            # with different precision.  So here we exploit the fact that numpy dtypes (at least for
            # numbers) order more or less by precision.
            dtype_list = [cat.dtype for cat in catalog_dict[key]]
            dtype_list.sort()
            dtypes.append((key, dtype_list[-1]))
        # Make sure that when we concatenate the arrays from different catalogs, we'l get the same
        # length for every column in catalog_dict.
        len_list = [sum([len(cat) for cat in catalog_dict[key]]) for key in catalog_dict]
        if not len(set(len_list))==1:
            raise RuntimeError('Different catalog lengths for different columns!')
        # Then make a blank array and fill it with the values from the arrays.
        data = numpy.zeros(len_list[0], dtype=dtypes)
        for key in catalog_dict:
            current_position = 0
            for catalog in catalog_dict[key]:
                data[key][current_position:current_position+len(catalog)] = catalog
                current_position+=len(catalog)
        return data

class VisitNoTractSingleEpochStileTask(VisitSingleEpochStileTask):
    """Like VisitSingleEpochStileTask, but we use a different argument parser that doesn't require
    an available coadd to run on the CCD level."""
    _DefaultName = "VisitNoTractSingleEpochStile"

    @classmethod
    def _makeArgumentParser(cls):
        parser = lsst.pipe.base.ArgumentParser(name=cls._DefaultName)
        parser.add_id_argument("--id", "src", help="data ID, with raw CCD keys")
        parser.description = parser_description
        return parser
