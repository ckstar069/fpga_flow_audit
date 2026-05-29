import numpy as np


def fixed_cfo_estimate(samples_q, preamble_q, q_frac=11):
    corr_i = (samples_q.real * preamble_q.real + samples_q.imag * preamble_q.imag) >> q_frac
    corr_q = (samples_q.imag * preamble_q.real - samples_q.real * preamble_q.imag) >> q_frac
    return corr_i, corr_q


def debug_dump(values_q, q_frac=11):
    float_vals = np.array(values_q, dtype=np.float64) / (1 << q_frac)
    return float_vals


def bad_uses_float(x):
    return float(x) * 1.5


def bad_uses_division(a, b):
    return a / b


def bad_uses_astype(arr):
    return arr.astype(np.float64)


def bad_uses_clip(val, lo, hi):
    return np.clip(val, lo, hi)


def bad_uses_complex_dtype(arr):
    return np.asarray(arr, dtype=np.complex128)


def bad_imports_config():
    import config.parameters
    return config.parameters.PARAMS