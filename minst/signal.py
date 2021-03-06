import claudio
import librosa
import logging
import numpy as np
import os
import pandas as pd
import scipy.signal as sig
import shutil

import minst.hll as H
import minst.utils as utils

logger = logging.getLogger(__name__)


def hll_onsets(filename, mfilt_len=51, threshold=0.5, wait=100):
    time_points, freqs, amps = H.hll(filename)
    freqs = sig.medfilt(freqs, mfilt_len)
    amps = sig.medfilt(amps, mfilt_len)

    voicings = (freqs * amps) > threshold
    c_n = utils.canny(25, 3.5, 1)

    novelty = sig.lfilter(c_n, [1], voicings > .5)
    onsets = novelty * (novelty > 0)
    onset_idx = librosa.onset.onset_detect(
        onset_envelope=onsets, wait=wait)

    if len(onset_idx):
        onset_times = time_points[onset_idx]
    else:
        onset_times = np.array([])
    # offsets = -novelty * (novelty < 0)
    # offset_idx = librosa.onset.onset_detect(
    #     onset_envelope=offsets, delta=delta, wait=wait)
    # offset_times = time_points[offset_idx]
    return onset_times  # , novelty, onsets, voicings


def logcqt(x, fs, hop_length=1024):
    """
    """
    x_noise = x + np.random.normal(scale=10.**-3, size=x.shape)
    cqt = librosa.cqt(x_noise.flatten(),
                      sr=fs, hop_length=hop_length, fmin=27.5,
                      n_bins=24 * 8, bins_per_octave=24, tuning=0,
                      sparsity=0, real=False, norm=1)
    cqt = np.abs(cqt)
    lcqt = np.log1p(5000 * cqt)
    return lcqt


def logcqt_onsets(x, fs, pre_max=0, post_max=1, pre_avg=0,
                  post_avg=1, delta=0.05, wait=50, hop_length=1024):
    """
    Parameters
    ----------
    x : np.ndarray
        Audio signal

    fs : scalar
        Samplerate of the audio signal.

    pre_max, post_max, pre_avg, post_avg, delta, wait
        See `librosa.util.peak_pick` for details.

    Returns
    -------
    onsets : np.ndarray, ndim=1
        Times in seconds for splitting.
    """
    lcqt = logcqt(x, fs, hop_length)
    c_n = utils.canny(51, 3.5, 1)
    onset_strength = sig.lfilter(c_n, np.ones(1), lcqt, axis=1).mean(axis=0)

    peak_idx = librosa.onset.onset_detect(
        onset_envelope=onset_strength, delta=delta, wait=wait)
    return librosa.frames_to_time(peak_idx, hop_length=hop_length)


def envelope_onsets(x, fs, wait=100):
    """
    Parameters
    ----------
    filename : str
        Path to an audiofile to split.

    Returns
    -------
    onsets : np.ndarray, ndim=1
        Times in seconds for splitting.
    """

    log_env = 10 * np.log10(10. ** -4.5 + np.power(x.flatten()[:], 2.0))
    w_n = np.hanning(100)
    w_n /= w_n.sum()
    log_env_lpf = sig.filtfilt(w_n, np.ones(1), log_env)

    n_hop = 100
    kernel = utils.canny(100, 3.5, 1)
    kernel /= np.abs(kernel).sum()
    onsets_forward = sig.lfilter(
        kernel, np.ones(1),
        log_env_lpf[::n_hop] - log_env_lpf.min(), axis=0)

    onsets_pos = onsets_forward * (onsets_forward > 0)
    peak_idx = librosa.util.peak_pick(onsets_pos,
                                      pre_max=500, post_max=500, pre_avg=10,
                                      post_avg=10, delta=0.025, wait=wait)
    return librosa.frames_to_time(peak_idx, hop_length=n_hop)


ONSETS = {
    'hll': hll_onsets,
    'logcqt': logcqt_onsets,
    'envelope': envelope_onsets
}


def log_envelope(x, fs, filt_len=100):
    log_env = 10 * np.log10(10.**-4.5 + np.power(x.flatten()[:], 2.0))
    w_n = np.hanning(filt_len)
    w_n /= w_n.sum()
    return sig.filtfilt(w_n, np.ones(1), log_env)


def segment(audio_file, mode, db_delta_thresh=2.5, **kwargs):
    x, fs = claudio.read(audio_file, samplerate=22050, channels=1, bytedepth=2)

    if mode == 'hll':
        onset_times = hll_onsets(audio_file)
    else:
        onset_times = ONSETS.get(mode)(x, fs, **kwargs)

    onset_idx = librosa.time_to_samples(onset_times, fs)

    log_env_lpf = log_envelope(x, fs, 100)
    recs = []
    for time, idx in zip(onset_times, onset_idx):
        x_m = log_env_lpf[idx: idx + int(fs)]
        if len(x_m) > 0:
            rec = dict(time=time, env_max=x_m.max(),
                       env_mean=x_m.mean(), env_std=x_m.std(),
                       env_delta=x_m.max() - log_env_lpf.mean())
            if rec['env_delta'] > db_delta_thresh:
                recs += [rec]

    return pd.DataFrame.from_records(recs)


def extract_clip(input_file, output_file, start_time, end_time,
                 duration=None, noise_floor=-65.0):
    """

    Returns
    -------
    success : bool
        True on successful extraction.
    """
    real_duration = end_time - start_time
    if duration is not None and real_duration >= duration:
        # We can use sox.trim without issue
        end_time = start_time + duration

    success = claudio.sox.trim(input_file, output_file, start_time, end_time)
    logger.debug("claudio.sox.trim: Success={} || {}[{}:{}] -> {}"
                 "".format(success, input_file, start_time, end_time,
                           output_file))

    noise_file = ''
    tmp_output_file = ''
    if duration is not None and real_duration < duration:
        # Generate noise pad signal
        sr = float(claudio.sox.soxi(input_file, 'r'))
        scale = (10.0**(noise_floor / 20.0)) / 2.0
        num_samples = int(sr * (duration - real_duration) + 0.5)
        noise_pad = np.random.normal(loc=0.0, scale=scale, size=(num_samples,))

        noise_file += claudio.util.temp_file('wav')
        tmp_output_file += claudio.util.temp_file(
            os.path.splitext(output_file)[-1].strip('.'))

        # Write, append, and move locally
        claudio.write(noise_file, noise_pad, sr)
        claudio.sox.concatenate([output_file, noise_file], tmp_output_file)
        os.rename(tmp_output_file, output_file)

    if os.path.exists(noise_file):
        os.remove(noise_file)

    if os.path.exists(tmp_output_file):
        os.remove(noise_file)

    return all([os.path.exists(output_file),
                not os.path.exists(noise_file),
                not os.path.exists(tmp_output_file)])
