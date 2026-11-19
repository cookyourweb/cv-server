"""Default deny in the namespace, then only the flows the API needs."""

import pytest

from helm_render import one, render_gke


@pytest.fixture(scope="module")
def gke():
    return render_gke()


def test_the_namespace_denies_all_traffic_by_default(gke):
    deny = one(gke, "NetworkPolicy", "cv-server-default-deny")
    assert deny["spec"]["podSelector"] == {}
    assert sorted(deny["spec"]["policyTypes"]) == ["Egress", "Ingress"]
    assert "ingress" not in deny["spec"] and "egress" not in deny["spec"]


def test_only_the_ingress_controller_and_helm_test_reach_the_api_port(gke):
    allow = one(gke, "NetworkPolicy", "cv-server-allow")
    assert allow["spec"]["podSelector"]["matchLabels"]["app"] == "cv-server"
    rules = allow["spec"]["ingress"]
    assert len(rules) == 1
    peers = rules[0]["from"]
    assert peers[0] == {
        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ingress-nginx"}},
        "podSelector": {"matchLabels": {"app.kubernetes.io/name": "ingress-nginx"}},
    }
    assert peers[1] == {"podSelector": {"matchLabels": {"app.kubernetes.io/component": "helm-test"}}}
    assert rules[0]["ports"] == [{"protocol": "TCP", "port": 8000}]


def test_egress_is_limited_to_dns_https_and_postgres(gke):
    allow = one(gke, "NetworkPolicy", "cv-server-allow")
    ports = sorted(p["port"] for rule in allow["spec"]["egress"] for p in rule["ports"])
    assert ports == [53, 53, 443, 5432]
    public = [r for r in allow["spec"]["egress"] if r.get("to")][0]["to"][0]["ipBlock"]
    assert public["cidr"] == "0.0.0.0/0"
    # Private ranges and the cluster Service range (where the Kubernetes API lives) stay closed.
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "34.118.224.0/20"):
        assert cidr in public["except"]


def test_the_helm_test_pod_may_only_call_the_api(gke):
    test = one(gke, "NetworkPolicy", "cv-server-helm-test")
    assert test["spec"]["podSelector"]["matchLabels"] == {"app.kubernetes.io/component": "helm-test"}
    assert test["spec"]["policyTypes"] == ["Egress"]
    to_api = test["spec"]["egress"][0]
    assert to_api["to"][0]["podSelector"]["matchLabels"]["app"] == "cv-server"
    assert to_api["ports"] == [{"protocol": "TCP", "port": 8000}]


def test_lets_encrypt_renewals_still_reach_the_acme_solver(gke):
    # cert-manager starts HTTP-01 solver pods in this namespace on every renewal.
    acme = one(gke, "NetworkPolicy", "cv-server-acme-solver")
    assert acme["spec"]["podSelector"]["matchLabels"] == {"acme.cert-manager.io/http01-solver": "true"}
    assert acme["spec"]["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 8089}]
