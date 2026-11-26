import pytest

from gupdater.demo import build_demo_context
from gupdater.report import run_scan


@pytest.fixture
def demo_ctx(tmp_path_factory):
    # A neutral folder name: test names such as "test_lesta" must not leak into paths.
    return build_demo_context(tmp_path_factory.mktemp("club") / "pc")


@pytest.fixture
def demo_scans(demo_ctx):
    return {scan.launcher_id: scan for scan in run_scan(demo_ctx).scans}
