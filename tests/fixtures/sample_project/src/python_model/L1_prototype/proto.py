from config.parameters import PARAMS
from L0_external.algo import compute_cfo


def run_estimation(signal, preamble):
    result = compute_cfo(signal, preamble)
    return result * PARAMS.scale