from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PROJECT = FIXTURES_DIR / "sample_project"


@pytest.fixture
def sample_project() -> Path:
    return SAMPLE_PROJECT