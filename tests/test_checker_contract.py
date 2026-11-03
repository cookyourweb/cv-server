from checker import AnalysisResult, Finding, Proposal, Status


def test_contract_minimo():
    resultado = AnalysisResult(
        status=Status.OK,
        findings=[Finding(type="gap", message="gap temporal")],
        proposals=[Proposal(type="section", message="añadir métricas", section="experiencia")],
        hash_cv="abc123",
        version_label="v1",
    ).to_dict()

    assert resultado["status"] in {"ok", "warning", "insufficient-content"}
    assert isinstance(resultado["findings"], list)
    assert isinstance(resultado["proposals"], list)
    assert resultado["hash_cv"]
    assert resultado["version_label"] == "v1"