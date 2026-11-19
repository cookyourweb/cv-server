"""Two replicas, a PDB and surge-first rolling updates: no downtime on deploys or drains."""

import pytest

from helm_render import SHA, by_kind, deployment, one, pod_spec, render, render_gke


@pytest.fixture(scope="module")
def gke():
    return render_gke()


def test_two_replicas_survive_a_voluntary_disruption(gke):
    hpa = one(gke, "HorizontalPodAutoscaler")
    assert hpa["spec"]["minReplicas"] >= 2
    pdb = one(gke, "PodDisruptionBudget")
    assert pdb["spec"]["minAvailable"] == 1
    assert pdb["spec"]["selector"]["matchLabels"] == deployment(gke)["spec"]["selector"]["matchLabels"]


def test_rolling_updates_never_drop_below_the_desired_replicas(gke):
    rolling = deployment(gke)["spec"]["strategy"]["rollingUpdate"]
    assert rolling == {"maxSurge": 1, "maxUnavailable": 0}


def test_replicas_are_spread_across_nodes(gke):
    spread = pod_spec(gke)["topologySpreadConstraints"][0]
    assert spread["topologyKey"] == "kubernetes.io/hostname"
    assert spread["maxSkew"] == 1
    assert spread["labelSelector"]["matchLabels"] == deployment(gke)["spec"]["selector"]["matchLabels"]


def test_a_single_replica_release_gets_no_pdb():
    # minAvailable 1 with one pod would block every node drain and upgrade.
    objects, proc = render(
        "--set", f"image.tag={SHA}",
        "--set", "autoscaling.enabled=false",
        "--set", "replicaCount=1",
    )
    assert proc.returncode == 0, proc.stderr
    assert by_kind(objects, "PodDisruptionBudget") == []
