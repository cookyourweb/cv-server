"""Secret Manager is the source of the env Secret, synced by External Secrets Operator."""

import pytest

from helm_render import SHA, by_kind, one, pod_spec, render, render_gke


@pytest.fixture(scope="module")
def gke():
    return render_gke()


def test_a_namespaced_store_reads_secret_manager_through_workload_identity(gke):
    store = one(gke, "SecretStore", "cv-server-gcp-secret-manager")
    gcpsm = store["spec"]["provider"]["gcpsm"]
    assert gcpsm["projectID"] == "cv-server-portfolio"
    wi = gcpsm["auth"]["workloadIdentity"]
    assert wi["serviceAccountRef"] == {"name": "cv-server-secrets"}
    assert wi["clusterName"] == "cv-server-cluster"
    assert wi["clusterLocation"] == "europe-west1-b"
    reader = one(gke, "ServiceAccount", "cv-server-secrets")
    assert reader["metadata"]["annotations"]["iam.gke.io/gcp-service-account"] == (
        "cv-server-secrets@cv-server-portfolio.iam.gserviceaccount.com"
    )
    # No pod runs as the reader: only ESO asks for its token.
    assert reader["automountServiceAccountToken"] is False


def test_the_external_secret_extracts_every_key_of_one_json_secret(gke):
    es = one(gke, "ExternalSecret", "cv-server-env")
    assert es["apiVersion"] == "external-secrets.io/v1"
    assert es["spec"]["secretStoreRef"] == {"kind": "SecretStore", "name": "cv-server-gcp-secret-manager"}
    assert es["spec"]["target"] == {"name": "cv-env-sm", "creationPolicy": "Owner", "deletionPolicy": "Retain"}
    assert es["spec"]["dataFrom"] == [{"extract": {"key": "cv-server-env", "version": "latest"}}]


def test_the_pod_reads_its_env_from_the_synced_secret(gke):
    container = pod_spec(gke)["containers"][0]
    assert container["envFrom"] == [{"secretRef": {"name": "cv-env-sm"}}]
    assert "env" not in container


def test_external_secrets_are_off_unless_asked_for():
    # The CRDs only exist once the operator is installed; the default must render without them.
    objects, proc = render(
        "--set", "image.repository=registry.example/cv-server", "--set", f"image.tag={SHA}",
        values_file=None,
    )
    assert proc.returncode == 0, proc.stderr
    assert by_kind(objects, "ExternalSecret") == []
    assert by_kind(objects, "SecretStore") == []
