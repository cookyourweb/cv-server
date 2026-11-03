import tempfile
from pathlib import Path

from checker import AnalysisResult, Finding, Proposal, Status, persistir_analisis, obtener_analisis_por_hash


def test_persistencia_no_duplica():
    with tempfile.TemporaryDirectory() as tmp:
        resultado = AnalysisResult(
            status=Status.OK,
            findings=[Finding(type="gap", message="gap temporal")],
            proposals=[Proposal(type="section", message="añadir métricas", section="experiencia")],
            hash_cv="hash-de-prueba",
            version_label="v1",
        )

        payload1 = persistir_analisis(resultado.hash_cv, resultado, storage_dir=Path(tmp))
        payload2 = persistir_analisis(resultado.hash_cv, resultado, storage_dir=Path(tmp))

        assert payload1 == payload2
        assert len(list(Path(tmp).glob("*.json"))) == 1

        recuperado = obtener_analisis_por_hash(resultado.hash_cv, storage_dir=Path(tmp))
        assert recuperado["hash_cv"] == resultado.hash_cv