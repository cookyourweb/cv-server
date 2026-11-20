"""helm/desplegar-manual.sh: the emergency deploy path refuses anything CI would not ship.

Each test builds a throwaway git repo (with a bare "origin") holding a copy of
the script, and puts fake kubectl/helm/gcloud first in PATH. The fakes record
their arguments, so no cluster or cloud is ever touched.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "helm" / "desplegar-manual.sh"
CONTEXT = "gke_cv-server-portfolio_europe-west1-b_cv-server-cluster"

if shutil.which("git") is None or shutil.which("bash") is None:
    pytest.skip("git and bash are required", allow_module_level=True)

FAKE = """#!/usr/bin/env bash
echo "{name} $*" >> "$FAKE_LOG"
{body}
"""


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    git(work, "config", "user.email", "t@example.invalid")
    git(work, "config", "user.name", "t")
    git(work, "config", "core.hooksPath", "/dev/null")
    (work / "helm").mkdir()
    shutil.copy(SCRIPT, work / "helm" / "desplegar-manual.sh")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "init")
    git(work, "push", "-q", "origin", "HEAD:main")
    return work


@pytest.fixture
def fakes(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("")
    state = {"context": CONTEXT, "image_exists": True}

    def write():
        bodies = {
            "kubectl": f'[[ "$1 $2" == "config current-context" ]] && echo "{state["context"]}"; exit 0',
            "gcloud": "exit 0" if state["image_exists"] else "echo 'NOT_FOUND' >&2; exit 1",
            "helm": '[[ "$1 $2" == "plugin list" ]] && echo "diff 3.15.15"; exit 0',
        }
        for name, body in bodies.items():
            f = bin_dir / name
            f.write_text(FAKE.format(name=name, body=body))
            f.chmod(0o755)

    write()
    state["write"] = write
    state["log"] = log
    state["bin"] = bin_dir
    return state


def run(repo, fakes, *args, stdin=""):
    env = dict(os.environ, PATH=f"{fakes['bin']}:{os.environ['PATH']}", FAKE_LOG=str(fakes["log"]))
    return subprocess.run(
        ["bash", str(repo / "helm" / "desplegar-manual.sh"), *args],
        cwd=repo, env=env, input=stdin, capture_output=True, text=True,
    )


def calls(fakes):
    return fakes["log"].read_text().splitlines()


def helm_mutations(fakes):
    return [c for c in calls(fakes) if c.startswith("helm upgrade") or c.startswith("helm rollback")]


def test_refuses_from_a_branch_other_than_main(repo, fakes):
    git(repo, "checkout", "-q", "-b", "infra/something")
    proc = run(repo, fakes, "--dry-run")
    assert proc.returncode == 1
    assert "main" in proc.stderr
    assert helm_mutations(fakes) == [] and not any(c.startswith("helm diff") for c in calls(fakes))


def test_refuses_with_uncommitted_changes(repo, fakes):
    (repo / "helm" / "extra.yaml").write_text("x: 1\n")
    proc = run(repo, fakes, "--dry-run")
    assert proc.returncode == 1
    assert "uncommitted" in proc.stderr


def test_refuses_a_commit_that_is_not_on_origin_main(repo, fakes):
    (repo / "local.txt").write_text("only here\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "unpushed")
    proc = run(repo, fakes, "--dry-run")
    assert proc.returncode == 1
    assert "origin/main" in proc.stderr


def test_refuses_the_wrong_kube_context(repo, fakes):
    fakes["context"] = "minikube"
    fakes["write"]()
    proc = run(repo, fakes, "--dry-run")
    assert proc.returncode == 1
    assert "minikube" in proc.stderr


def test_refuses_an_image_ci_never_built(repo, fakes):
    fakes["image_exists"] = False
    fakes["write"]()
    proc = run(repo, fakes, "--dry-run")
    assert proc.returncode == 1
    assert "not in Artifact Registry" in proc.stderr
    assert helm_mutations(fakes) == []


def sha(repo):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()


def test_dry_run_shows_the_diff_for_the_exact_sha_and_changes_nothing(repo, fakes):
    proc = run(repo, fakes, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    diff = [c for c in calls(fakes) if c.startswith("helm diff upgrade")]
    assert len(diff) == 1
    assert f"image.tag={sha(repo)}" in diff[0]
    assert "values.gke.yaml" in diff[0]
    assert helm_mutations(fakes) == []


def test_a_wrong_confirmation_deploys_nothing(repo, fakes):
    proc = run(repo, fakes, stdin="yes\n")
    assert proc.returncode == 1
    assert helm_mutations(fakes) == []


def test_the_typed_short_sha_deploys_atomically_and_runs_helm_test(repo, fakes):
    proc = run(repo, fakes, stdin=sha(repo)[:7] + "\n")
    assert proc.returncode == 0, proc.stderr
    upgrade = helm_mutations(fakes)
    assert len(upgrade) == 1
    assert "--atomic" in upgrade[0] and f"image.tag={sha(repo)}" in upgrade[0]
    assert any(c.startswith("helm test cv-server") for c in calls(fakes))
