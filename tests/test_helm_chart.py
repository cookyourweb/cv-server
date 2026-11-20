"""The chart renders one reproducible, internal-only, restricted workload."""

import pytest

from helm_render import SHA, by_kind, one, pod_spec, render, render_gke


@pytest.fixture(scope="module")
def gke():
    return render_gke()


# --- Reproducible image reference -------------------------------------------

def test_render_without_an_image_tag_fails():
    _, proc = render()
    assert proc.returncode != 0
    assert "tag" in proc.stderr


@pytest.mark.parametrize("tag", ["latest", "prod", "814a90b-dirty", "814a90b"])
def test_only_full_commit_sha_tags_are_accepted(tag):
    # A short or mutable tag cannot be traced back to exactly one build.
    _, proc = render("--set", f"image.tag={tag}")
    assert proc.returncode != 0, f"tag {tag!r} should be rejected"


def test_the_image_is_pinned_to_the_sha(gke):
    container = pod_spec(gke)["containers"][0]
    assert container["image"] == (
        f"europe-west1-docker.pkg.dev/cv-server-portfolio/cv-server/cv-server:{SHA}"
    )
    # Immutable tags make Always pointless and add a registry round-trip per start.
    assert container["imagePullPolicy"] == "IfNotPresent"


# --- Exposure ------------------------------------------------------------------

def test_the_service_is_internal_only(gke):
    # A LoadBalancer Service published plain HTTP next to the TLS ingress.
    assert one(gke, "Service")["spec"]["type"] == "ClusterIP"


def test_the_ingress_is_rendered_with_tls_for_the_api_host(gke):
    ingress = one(gke, "Ingress", "cv-server-ingress")
    assert ingress["spec"]["ingressClassName"] == "nginx"
    assert ingress["spec"]["tls"] == [{"hosts": ["api.cookyourwebai.es"], "secretName": "cv-server-tls"}]
    annotations = ingress["metadata"]["annotations"]
    assert annotations["cert-manager.io/cluster-issuer"] == "letsencrypt-prod"
    assert annotations["nginx.ingress.kubernetes.io/ssl-redirect"] == "true"
    backend = ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]
    assert backend == {"name": "cv-server-cv-server", "port": {"number": 80}}


# --- Pod security (Pod Security Admission "restricted") ----------------------

def test_the_pod_meets_the_restricted_pod_security_standard(gke):
    spec = pod_spec(gke)
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert spec["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    for c in spec["containers"]:
        sc = c["securityContext"]
        assert sc["allowPrivilegeEscalation"] is False
        assert sc["capabilities"]["drop"] == ["ALL"]
        assert sc["readOnlyRootFilesystem"] is True


def test_the_pod_runs_with_its_own_service_account_and_no_api_token(gke):
    sa = one(gke, "ServiceAccount", "cv-server")
    assert sa["automountServiceAccountToken"] is False
    spec = pod_spec(gke)
    assert spec["serviceAccountName"] == "cv-server"
    assert spec["automountServiceAccountToken"] is False


# --- helm test ----------------------------------------------------------------

def test_helm_test_checks_health_with_the_app_image(gke):
    tests = [o for o in by_kind(gke, "Pod") if o["metadata"]["annotations"].get("helm.sh/hook") == "test"]
    assert len(tests) == 1
    pod = tests[0]["spec"]
    assert pod["restartPolicy"] == "Never"
    assert pod["containers"][0]["image"].endswith(f":{SHA}")
    assert "/health" in " ".join(pod["containers"][0]["command"])
    assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    assert pod["automountServiceAccountToken"] is False
