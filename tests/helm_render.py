"""Helpers to render the Helm chart in tests.

Nothing here touches a cluster: `helm template` renders locally. Test modules
that import this are skipped when the `helm` binary or PyYAML is missing, so the
app suite keeps running on machines without the infra tooling (CI has both).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

if shutil.which("helm") is None:
    pytest.skip("helm is not installed", allow_module_level=True)

CHART = Path(__file__).resolve().parent.parent / "helm" / "cv-server-chart"
GKE_VALUES = CHART / "values.gke.yaml"
SHA = "0123456789abcdef0123456789abcdef01234567"


def render(*args, values_file=GKE_VALUES):
    """Render the chart and return (objects, completed process)."""
    cmd = ["helm", "template", "cv-server", str(CHART), "--namespace", "default"]
    if values_file is not None:
        cmd += ["-f", str(values_file)]
    cmd += list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    objects = []
    if proc.returncode == 0:
        objects = [d for d in yaml.safe_load_all(proc.stdout) if d]
    return objects, proc


def render_gke():
    objects, proc = render("--set", f"image.tag={SHA}")
    assert proc.returncode == 0, proc.stderr
    return objects


def by_kind(objects, kind):
    return [o for o in objects if o["kind"] == kind]


def one(objects, kind, name=None):
    found = [o for o in by_kind(objects, kind) if name is None or o["metadata"]["name"] == name]
    assert len(found) == 1, f"expected one {kind} {name or ''}, got {len(found)}"
    return found[0]


def deployment(objects):
    return one(objects, "Deployment")


def pod_spec(objects):
    return deployment(objects)["spec"]["template"]["spec"]
