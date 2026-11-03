from checker import detectar_gaps_temporales


def test_gap_detectado():
    texto = "Desarrollador 2019-2020\nAnalista 2023-2024"
    assert len(detectar_gaps_temporales(texto)) == 1


def test_sin_gap():
    texto = "Desarrollador 2022-2023\nAnalista 2024-2025"
    assert detectar_gaps_temporales(texto) == []