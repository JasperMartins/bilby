import numpy as np
from scipy.signal.windows import tukey

from bilby.core import utils
from bilby.core.series import CoupledTimeAndFrequencySeries
from bilby.core.utils import logger
from bilby.gw import utils as gwutils

try:
    import gwpy
    import gwpy.signal
except ImportError:
    logger.warning("You do not have gwpy installed currently. You will "
                   " not be able to use some of the prebuilt functions.")

try:
    import lal
except ImportError:
    logger.warning("You do not have lalsuite installed currently. You will"
                   " not be able to use some of the prebuilt functions.")


class InterferometerStrainData(object):
    """ Strain data for an interferometer """

    def __init__(self, minimum_frequency=0, maximum_frequency=np.inf,
                 roll_off=0.2):
        """ Initiate an InterferometerStrainData object

        The initialised object contains no data, this should be added using one
        of the `set_from..` methods.

        Parameters
        ----------
        minimum_frequency: float
            Minimum frequency to analyse for detector. Default is 0.
        maximum_frequency: float
            Maximum frequency to analyse for detector. Default is infinity.
        roll_off: float
            The roll-off (in seconds) used in the Tukey window, default=0.2s.
            This corresponds to alpha * duration / 2 for scipy tukey window.

        """
        self.minimum_frequency = minimum_frequency
        self.maximum_frequency = maximum_frequency
        self.roll_off = roll_off
        self.window_factor = 1

        self._times_and_frequencies = CoupledTimeAndFrequencySeries()
        # self._set_time_and_frequency_array_parameters(None, None, None)

        self._frequency_domain_strain = None
        self._frequency_array = None
        self._time_domain_strain = None
        self._time_array = None
        self._channel = None

    def __eq__(self, other):
        if self.minimum_frequency == other.minimum_frequency \
                and self.maximum_frequency == other.maximum_frequency \
                and self.roll_off == other.roll_off \
                and self.window_factor == other.window_factor \
                and self.sampling_frequency == other.sampling_frequency \
                and self.duration == other.duration \
                and self.start_time == other.start_time \
                and np.array_equal(self.time_array, other.time_array) \
                and np.array_equal(self.frequency_array, other.frequency_array) \
                and np.array_equal(self.frequency_domain_strain, other.frequency_domain_strain) \
                and np.array_equal(self.time_domain_strain, other.time_domain_strain):
            return True
        return False

    def time_within_data(self, time):
        """ Check if time is within the data span

        Parameters
        ----------
        time: float
            The time to check

        Returns
        -------
        bool:
            A boolean stating whether the time is inside or outside the span

        """
        if time < self.start_time:
            logger.debug("Time is before the start_time")
            return False
        elif time > self.start_time + self.duration:
            logger.debug("Time is after the start_time + duration")
            return False
        else:
            return True

    @property
    def minimum_frequency(self):
        return self.__minimum_frequency

    @minimum_frequency.setter
    def minimum_frequency(self, minimum_frequency):
        self.__minimum_frequency = minimum_frequency

    @property
    def maximum_frequency(self):
        """ Force the maximum frequency be less than the Nyquist frequency """
        if self.sampling_frequency is not None:
            if 2 * self.__maximum_frequency > self.sampling_frequency:
                self.__maximum_frequency = self.sampling_frequency / 2.
        return self.__maximum_frequency

    @maximum_frequency.setter
    def maximum_frequency(self, maximum_frequency):
        self.__maximum_frequency = maximum_frequency

    @property
    def frequency_mask(self):
        """Masking array for limiting the frequency band.

        Returns
        -------
        array_like: An array of boolean values
        """
        try:
            return self._frequency_mask
        except AttributeError:
            frequency_array = self._times_and_frequencies.frequency_array
            mask = ((frequency_array >= self.minimum_frequency) &
                    (frequency_array <= self.maximum_frequency))
            self._frequency_mask = mask
            return self._frequency_mask

    @property
    def alpha(self):
        return 2 * self.roll_off / self.duration

    def time_domain_window(self, roll_off=None, alpha=None):
        """
        Window function to apply to time domain data before FFTing.

        This defines self.window_factor as the power loss due to the windowing.
        See https://dcc.ligo.org/DocDB/0027/T040089/000/T040089-00.pdf

        Parameters
        ----------
        roll_off: float
            Rise time of window in seconds
        alpha: float
            Parameter to pass to tukey window, how much of segment falls
            into windowed part

        Return
        ------
        window: array
            Window function over time array
        """
        if roll_off is not None:
            self.roll_off = roll_off
        elif alpha is not None:
            self.roll_off = alpha * self.duration / 2
        window = tukey(len(self._time_domain_strain), alpha=self.alpha)
        self.window_factor = np.mean(window ** 2)
        return window

    @property
    def time_domain_strain(self):
        """ The time domain strain, in units of strain """
        if self._time_domain_strain is not None:
            return self._time_domain_strain
        elif self._frequency_domain_strain is not None:
            self._time_domain_strain = utils.infft(
                self.frequency_domain_strain, self.sampling_frequency)
            return self._time_domain_strain

        else:
            raise ValueError("time domain strain data not yet set")

    @property
    def frequency_domain_strain(self):
        """ Returns the frequency domain strain

        This is the frequency domain strain normalised to units of
        strain / Hz, obtained by a one-sided Fourier transform of the
        time domain data, divided by the sampling frequency.
        """
        if self._frequency_domain_strain is not None:
            return self._frequency_domain_strain * self.frequency_mask
        elif self._time_domain_strain is not None:
            logger.info("Generating frequency domain strain from given time "
                        "domain strain.")
            logger.info("Applying a tukey window with alpha={}, roll off={}".format(
                self.alpha, self.roll_off))
            # self.low_pass_filter()
            window = self.time_domain_window()
            self._frequency_domain_strain, self.frequency_array = utils.nfft(
                self._time_domain_strain * window, self.sampling_frequency)
            return self._frequency_domain_strain * self.frequency_mask
        else:
            raise ValueError("frequency domain strain data not yet set")

    @frequency_domain_strain.setter
    def frequency_domain_strain(self, frequency_domain_strain):
        if not len(self.frequency_array) == len(frequency_domain_strain):
            raise ValueError("The frequency_array and the set strain have different lengths")
        self._frequency_domain_strain = frequency_domain_strain

    def to_gwpy_timeseries(self):
        """
        Output the time series strain data as a :class:`gwpy.timeseries.TimeSeries`.
        """

        return gwpy.timeseries.TimeSeries(self.time_domain_strain,
                                          sample_rate=self.sampling_frequency,
                                          t0=self.start_time,
                                          channel=self.channel)

    def to_pycbc_timeseries(self):
        """
        Output the time series strain data as a :class:`pycbc.types.timeseries.TimeSeries`.
        """

        try:
            import pycbc
        except ImportError:
            raise ImportError("Cannot output strain data as PyCBC TimeSeries")

        return pycbc.types.timeseries.TimeSeries(self.time_domain_strain,
                                                 delta_t=(1. / self.sampling_frequency),
                                                 epoch=lal.LIGOTimeGPS(self.start_time))

    def to_lal_timeseries(self):
        """
        Output the time series strain data as a LAL TimeSeries object.
        """

        laldata = lal.CreateREAL8TimeSeries("",
                                            lal.LIGOTimeGPS(self.start_time),
                                            0., (1. / self.sampling_frequency),
                                            lal.SecondUnit,
                                            len(self.time_domain_strain))
        laldata.data.data[:] = self.time_domain_strain

        return laldata

    def to_gwpy_frequencyseries(self):
        """
        Output the frequency series strain data as a :class:`gwpy.frequencyseries.FrequencySeries`.
        """

        return gwpy.frequencyseries.FrequencySeries(self.frequency_domain_strain,
                                                    frequencies=self.frequency_array,
                                                    epoch=self.start_time,
                                                    channel=self.channel)

    def to_pycbc_frequencyseries(self):
        """
        Output the frequency series strain data as a :class:`pycbc.types.frequencyseries.FrequencySeries`.
        """

        try:
            import pycbc
        except ImportError:
            raise ImportError("Cannot output strain data as PyCBC FrequencySeries")

        return pycbc.types.frequencyseries.FrequencySeries(self.frequency_domain_strain,
                                                           delta_f=(self.frequency_array[1] - self.frequency_array[0]),
                                                           epoch=lal.LIGOTimeGPS(self.start_time))

    def to_lal_frequencyseries(self):
        """
        Output the frequency series strain data as a LAL FrequencySeries object.
        """

        laldata = lal.CreateCOMPLEX16FrequencySeries("",
                                                     lal.LIGOTimeGPS(self.start_time),
                                                     self.frequency_array[0],
                                                     (self.frequency_array[1] - self.frequency_array[0]),
                                                     lal.SecondUnit,
                                                     len(self.frequency_domain_strain))
        laldata.data.data[:] = self.frequency_domain_strain

        return laldata

    def add_to_frequency_domain_strain(self, x):
        """Deprecated"""
        self._frequency_domain_strain += x

    def low_pass_filter(self, filter_freq=None):
        """ Low pass filter the data """

        if filter_freq is None:
            logger.debug(
                "Setting low pass filter_freq using given maximum frequency")
            filter_freq = self.maximum_frequency

        if 2 * filter_freq >= self.sampling_frequency:
            logger.info(
                "Low pass filter frequency of {}Hz requested, this is equal"
                " or greater than the Nyquist frequency so no filter applied"
                .format(filter_freq))
            return

        logger.debug("Applying low pass filter with filter frequency {}".format(filter_freq))
        bp = gwpy.signal.filter_design.lowpass(
            filter_freq, self.sampling_frequency)
        strain = gwpy.timeseries.TimeSeries(
            self.time_domain_strain, sample_rate=self.sampling_frequency)
        strain = strain.filter(bp, filtfilt=True)
        self._time_domain_strain = strain.value

    def create_power_spectral_density(
            self, fft_length, overlap=0, name='unknown', outdir=None,
            analysis_segment_start_time=None):
        """ Use the time domain strain to generate a power spectral density

        This create a Tukey-windowed power spectral density and writes it to a
        PSD file.

        Parameters
        ----------
        fft_length: float
            Duration of the analysis segment.
        overlap: float
            Number of seconds of overlap between FFTs.
        name: str
            The name of the detector, used in storing the PSD. Defaults to
            "unknown".
        outdir: str
            The output directory to write the PSD file too. If not given,
            the PSD will not be written to file.
        analysis_segment_start_time: float
            The start time of the analysis segment, if given, this data will
            be removed before creating the PSD.

        Returns
        -------
        frequency_array, psd : array_like
            The frequencies and power spectral density array

        """

        data = self.time_domain_strain

        if analysis_segment_start_time is not None:
            analysis_segment_end_time = analysis_segment_start_time + fft_length
            inside = (analysis_segment_start_time > self.time_array[0] +
                      analysis_segment_end_time < self.time_array[-1])
            if inside:
                logger.info("Removing analysis segment data from the PSD data")
                idxs = (
                    (self.time_array < analysis_segment_start_time) +
                    (self.time_array > analysis_segment_end_time))
                data = data[idxs]

        # WARNING this line can cause issues if the data is non-contiguous
        strain = gwpy.timeseries.TimeSeries(data=data, sample_rate=self.sampling_frequency)
        psd_alpha = 2 * self.roll_off / fft_length
        logger.info(
            "Tukey window PSD data with alpha={}, roll off={}".format(
                psd_alpha, self.roll_off))
        psd = strain.psd(
            fftlength=fft_length, overlap=overlap, window=('tukey', psd_alpha))

        if outdir:
            psd_file = '{}/{}_PSD_{}_{}.txt'.format(outdir, name, self.start_time, self.duration)
            with open('{}'.format(psd_file), 'w+') as opened_file:
                for f, p in zip(psd.frequencies.value, psd.value):
                    opened_file.write('{} {}\n'.format(f, p))

        return psd.frequencies.value, psd.value

    def _infer_time_domain_dependence(
            self, start_time, sampling_frequency, duration, time_array):
        """ Helper function to figure out if the time_array, or
            sampling_frequency and duration where given
        """
        self._infer_dependence(domain='time', array=time_array, duration=duration,
                               sampling_frequency=sampling_frequency, start_time=start_time)

    def _infer_frequency_domain_dependence(
            self, start_time, sampling_frequency, duration, frequency_array):
        """ Helper function to figure out if the frequency_array, or
            sampling_frequency and duration where given
        """

        self._infer_dependence(domain='frequency', array=frequency_array,
                               duration=duration, sampling_frequency=sampling_frequency, start_time=start_time)

    def _infer_dependence(self, domain, array, duration, sampling_frequency, start_time):
        if (sampling_frequency is not None) and (duration is not None):
            if array is not None:
                raise ValueError(
                    "You have given the sampling_frequency, duration, and "
                    "an array")
            pass
        elif array is not None:
            if domain == 'time':
                self.time_array = array
            elif domain == 'frequency':
                self.frequency_array = array
            return
        elif sampling_frequency is None or duration is None:
            raise ValueError(
                "You must provide both sampling_frequency and duration")
        else:
            raise ValueError(
                "Insufficient information given to set arrays")
        self._set_time_and_frequency_array_parameters(duration=duration,
                                                      sampling_frequency=sampling_frequency,
                                                      start_time=start_time)

    def set_from_time_domain_strain(
            self, time_domain_strain, sampling_frequency=None, duration=None,
            start_time=0, time_array=None):
        """ Set the strain data from a time domain strain array

        This sets the time_domain_strain attribute, the frequency_domain_strain
        is automatically calculated after a low-pass filter and Tukey window
        is applied.

        Parameters
        ----------
        time_domain_strain: array_like
            An array of the time domain strain.
        sampling_frequency: float
            The sampling frequency (in Hz).
        duration: float
            The data duration (in s).
        start_time: float
            The GPS start-time of the data.
        time_array: array_like
            The array of times, if sampling_frequency and duration not
            given.

        """
        self._infer_time_domain_dependence(start_time=start_time,
                                           sampling_frequency=sampling_frequency,
                                           duration=duration,
                                           time_array=time_array)

        logger.debug('Setting data using provided time_domain_strain')
        if np.shape(time_domain_strain) == np.shape(self.time_array):
            self._time_domain_strain = time_domain_strain
            self._frequency_domain_strain = None
        else:
            raise ValueError("Data times do not match time array")

    def set_from_gwpy_timeseries(self, time_series):
        """ Set the strain data from a gwpy TimeSeries

        This sets the time_domain_strain attribute, the frequency_domain_strain
        is automatically calculated after a low-pass filter and Tukey window
        is applied.

        Parameters
        ----------
        time_series: gwpy.timeseries.timeseries.TimeSeries

        """
        logger.debug('Setting data using provided gwpy TimeSeries object')
        if type(time_series) != gwpy.timeseries.TimeSeries:
            raise ValueError("Input time_series is not a gwpy TimeSeries")
        self._set_time_and_frequency_array_parameters(duration=time_series.duration.value,
                                                      sampling_frequency=time_series.sample_rate.value,
                                                      start_time=time_series.epoch.value)
        self._time_domain_strain = time_series.value
        self._frequency_domain_strain = None
        self._channel = time_series.channel

    @property
    def channel(self):
        return self._channel

    def set_from_open_data(
            self, name, start_time, duration=4, outdir='outdir', cache=True,
            **kwargs):
        """ Set the strain data from open LOSC data

        This sets the time_domain_strain attribute, the frequency_domain_strain
        is automatically calculated after a low-pass filter and Tukey window
        is applied.

        Parameters
        ----------
        name: str
            Detector name, e.g., 'H1'.
        start_time: float
            Start GPS time of segment.
        duration: float, optional
            The total time (in seconds) to analyse. Defaults to 4s.
        outdir: str
            Directory where the psd files are saved
        cache: bool, optional
            Whether or not to store/use the acquired data.
        **kwargs:
            All keyword arguments are passed to
            `gwpy.timeseries.TimeSeries.fetch_open_data()`.

        """

        timeseries = gwutils.get_open_strain_data(
            name, start_time, start_time + duration, outdir=outdir, cache=cache,
            **kwargs)

        self.set_from_gwpy_timeseries(timeseries)

    def set_from_csv(self, filename):
        """ Set the strain data from a csv file

        Parameters
        ----------
        filename: str
            The path to the file to read in

        """
        timeseries = gwpy.timeseries.TimeSeries.read(filename, format='csv')
        self.set_from_gwpy_timeseries(timeseries)

    def set_from_frequency_domain_strain(
            self, frequency_domain_strain, sampling_frequency=None,
            duration=None, start_time=0, frequency_array=None):
        """ Set the `frequency_domain_strain` from a numpy array

        Parameters
        ----------
        frequency_domain_strain: array_like
            The data to set.
        sampling_frequency: float
            The sampling frequency (in Hz).
        duration: float
            The data duration (in s).
        start_time: float
            The GPS start-time of the data.
        frequency_array: array_like
            The array of frequencies, if sampling_frequency and duration not
            given.

        """

        self._infer_frequency_domain_dependence(start_time=start_time,
                                                sampling_frequency=sampling_frequency,
                                                duration=duration,
                                                frequency_array=frequency_array)

        logger.debug('Setting data using provided frequency_domain_strain')
        if np.shape(frequency_domain_strain) == np.shape(self.frequency_array):
            self._frequency_domain_strain = frequency_domain_strain
            self.window_factor = 1
        else:
            raise ValueError("Data frequencies do not match frequency_array")

    def set_from_power_spectral_density(
            self, power_spectral_density, sampling_frequency, duration,
            start_time=0):
        """ Set the `frequency_domain_strain` by generating a noise realisation

        Parameters
        ----------
        power_spectral_density: bilby.gw.detector.PowerSpectralDensity
            A PowerSpectralDensity object used to generate the data
        sampling_frequency: float
            The sampling frequency (in Hz)
        duration: float
            The data duration (in s)
        start_time: float
            The GPS start-time of the data

        """

        self._set_time_and_frequency_array_parameters(duration=duration,
                                                      sampling_frequency=sampling_frequency,
                                                      start_time=start_time)

        logger.debug(
            'Setting data using noise realization from provided'
            'power_spectal_density')
        frequency_domain_strain, frequency_array = \
            power_spectral_density.get_noise_realisation(
                self.sampling_frequency, self.duration)

        if np.array_equal(frequency_array, self.frequency_array):
            self._frequency_domain_strain = frequency_domain_strain
        else:
            raise ValueError("Data frequencies do not match frequency_array")

    def set_from_zero_noise(self, sampling_frequency, duration, start_time=0):
        """ Set the `frequency_domain_strain` to zero noise

        Parameters
        ----------
        sampling_frequency: float
            The sampling frequency (in Hz)
        duration: float
            The data duration (in s)
        start_time: float
            The GPS start-time of the data

        """

        self._set_time_and_frequency_array_parameters(duration=duration,
                                                      sampling_frequency=sampling_frequency,
                                                      start_time=start_time)

        logger.debug('Setting zero noise data')
        self._frequency_domain_strain = np.zeros_like(self.frequency_array,
                                                      dtype=np.complex)

    def set_from_frame_file(
            self, frame_file, sampling_frequency, duration, start_time=0,
            channel=None, buffer_time=1):
        """ Set the `frequency_domain_strain` from a frame fiile

        Parameters
        ----------
        frame_file: str
            File from which to load data.
        channel: str
            Channel to read from frame.
        sampling_frequency: float
            The sampling frequency (in Hz)
        duration: float
            The data duration (in s)
        start_time: float
            The GPS start-time of the data
        buffer_time: float
            Read in data with `start_time-buffer_time` and
            `start_time+duration+buffer_time`

        """

        self._set_time_and_frequency_array_parameters(duration=duration,
                                                      sampling_frequency=sampling_frequency,
                                                      start_time=start_time)

        logger.info('Reading data from frame file {}'.format(frame_file))
        strain = gwutils.read_frame_file(
            frame_file, start_time=start_time, end_time=start_time + duration,
            buffer_time=buffer_time, channel=channel,
            resample=sampling_frequency)

        self.set_from_gwpy_timeseries(strain)

    def _set_time_and_frequency_array_parameters(self, duration, sampling_frequency, start_time):
        self._times_and_frequencies = CoupledTimeAndFrequencySeries(duration=duration,
                                                                    sampling_frequency=sampling_frequency,
                                                                    start_time=start_time)

    @property
    def sampling_frequency(self):
        return self._times_and_frequencies.sampling_frequency

    @sampling_frequency.setter
    def sampling_frequency(self, sampling_frequency):
        self._times_and_frequencies.sampling_frequency = sampling_frequency

    @property
    def duration(self):
        return self._times_and_frequencies.duration

    @duration.setter
    def duration(self, duration):
        self._times_and_frequencies.duration = duration

    @property
    def start_time(self):
        return self._times_and_frequencies.start_time

    @start_time.setter
    def start_time(self, start_time):
        self._times_and_frequencies.start_time = start_time

    @property
    def frequency_array(self):
        """ Frequencies of the data in Hz """
        return self._times_and_frequencies.frequency_array

    @frequency_array.setter
    def frequency_array(self, frequency_array):
        self._times_and_frequencies.frequency_array = frequency_array

    @property
    def time_array(self):
        """ Time of the data in seconds """
        return self._times_and_frequencies.time_array

    @time_array.setter
    def time_array(self, time_array):
        self._times_and_frequencies.time_array = time_array