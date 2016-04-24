import claudio
import librosa
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.signal as sig

import minst.hll as H
import minst.utils as utils


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
    print(onset_idx)
    if len(onset_idx):
        onset_times = time_points[onset_idx]
    else:
        onset_times = np.array([])
    # offsets = -novelty * (novelty < 0)
    # offset_idx = librosa.onset.onset_detect(
    #     onset_envelope=offsets, delta=delta, wait=wait)
    # offset_times = time_points[offset_idx]
    return onset_times  # , novelty, onsets, voicings


def logcqt_onsets(x, fs, pre_max=0, post_max=1, pre_avg=0,
                  post_avg=1, delta=0.05, wait=50):
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
    hop_length = 1024
    x_noise = x + np.random.normal(scale=10.**-3, size=x.shape)
    cqt = librosa.cqt(x_noise.flatten(),
                      sr=fs, hop_length=hop_length, fmin=27.5,
                      n_bins=24*8, bins_per_octave=24, tuning=0,
                      sparsity=0, real=False, norm=1)
    cqt = np.abs(cqt)
    lcqt = np.log1p(5000*cqt)

    c_n = utils.canny(51, 3.5, 1)
    onset_strength = sig.lfilter(c_n, np.ones(1), lcqt, axis=1).mean(axis=0)

    peak_idx = librosa.onset.onset_detect(
        onset_envelope=onset_strength, delta=delta, wait=wait)
    return librosa.frames_to_time(peak_idx, hop_length=hop_length)


def envelope_onsets(x, fs):
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

    log_env = 10*np.log10(10.**-4.5 + np.power(x.flatten()[:], 2.0))
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
                                      post_avg=10, delta=0.025, wait=100)
    return librosa.frames_to_time(peak_idx, hop_length=n_hop)


ONSETS = {
    'hll': hll_onsets,
    'logcqt': logcqt_onsets,
    'envelope': envelope_onsets
}


def segment(filename, mode, **kwargs):
    x, fs = claudio.read(filename, samplerate=22050, channels=1, bytedepth=2)

    if mode == 'hll':
        onset_times = hll_onsets(filename)
    else:
        onset_times = ONSETS.get(mode)(x, fs, **kwargs)

    print(onset_times)

    log_env = 10*np.log10(10.**-4.5 + np.power(x.flatten()[:], 2.0))
    w_n = np.hanning(100)
    w_n /= w_n.sum()
    log_env_lpf = sig.filtfilt(w_n, np.ones(1), log_env)
    onset_idx = librosa.time_to_samples(onset_times, fs)

    recs = []
    for time, idx in zip(onset_times, onset_idx):
        x_m = log_env_lpf[idx: idx + int(fs)]
        recs += [dict(time=time, env_max=x_m.max(),
                      env_mean=x_m.mean(), env_std=x_m.std(),
                      env_delta=x_m.max() - log_env_lpf.min())]

    fig, axes = plt.subplots(nrows=2, ncols=1, figsize=(12, 6))
    nhop = 100
    x_max = np.abs(x).max()
    trange = np.arange(0, len(x), nhop) / float(fs)

    axes[0].plot(trange, x.flatten()[::nhop])
    axes[0].vlines(onset_times, ymin=-1.05*x_max, ymax=1.05*x_max, color='k',
                   alpha=0.5, linewidth=3)

    axes[1].plot(trange, log_env_lpf[::nhop])
    axes[1].vlines(onset_times, ymin=log_env_lpf.min()*1.05,
                   ymax=0, color='k', alpha=0.5, linewidth=3)

    for ax in axes:
        ax.set_xlim(0, trange.max())
        ax.set_xlabel("Time (sec)")

    axes[0].set_title("{} - {}".format(mode, filename))

    return pd.DataFrame.from_records(recs), fig
