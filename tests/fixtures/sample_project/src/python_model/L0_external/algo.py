import numpy as np


def compute_cfo(samples, preamble):
    corr = np.conj(preamble) * samples
    angle = np.angle(corr)
    return angle


def estimate_offset(signal):
    return np.mean(signal)