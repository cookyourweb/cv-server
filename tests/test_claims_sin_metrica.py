from checker import detectar_claims_sin_metrica


def test_claim_sin_metrica():
    texto = "Reduje costes de infraestructura\nMejoré latencia"
    assert len(detectar_claims_sin_metrica(texto)) == 2


def test_claim_con_metrica():
    texto = "Reduje costes de infraestructura un 20%\nMejoré latencia en 50 ms"
    assert detectar_claims_sin_metrica(texto) == []