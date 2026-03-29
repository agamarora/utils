"""POSIX platform stubs — placeholders for Linux/Mac implementations (v2).

All functions return empty/default values. The architecture is ready
for real implementations when cross-platform support is added.
"""


def init_drive_map() -> dict:
    return {}


def get_drive_to_disk() -> dict:
    return {}


def init_pdh():
    pass


def collect_disk_active() -> dict:
    return {}


def collect_temps_lhm() -> dict:
    return {}


def get_lhm_clocks() -> dict:
    return {}


def get_lhm_freq_str() -> tuple[str, float]:
    return "", 0.0
