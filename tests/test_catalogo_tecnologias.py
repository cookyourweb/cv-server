"""TDD - una tecnologia compuesta no puede disparar tambien su nombre corto.

Caso encontrado el 28-ago-2026 al preparar la extraccion de `guardrails.py`:
`_tecnologias_en` estaba definida DOS veces en `server.py`, en las
lineas 406 y 690. La segunda pisaba a la primera, asi que la que se ejecutaba
era la ingenua.

La de la 406 consume los tramos ya reconocidos, y su docstring dice por que:
"para que un nombre corto no vuelva a saltar dentro de uno largo que ya se ha
identificado". La de la 690 comprueba cada alias por separado.

En textos normales las dos dan lo mismo: el limite de palabra hace el trabajo.
La diferencia sale con tecnologias de VARIAS PALABRAS, donde el espacio del
medio no es caracter de palabra y el patron corto salta igual:

    "react native"   ->  {React Native}              (correcto)
    "react native"   ->  {React, React Native}       (ingenua: se inventa React)

Importa porque `detectar_tecnologias_no_respaldadas` resta lo del CV menos lo
del Master: una tecnologia fantasma en cualquiera de los dos lados mueve el
resultado de un guardrail de veracidad.
"""
import server as srv


def test_react_native_no_dispara_react():
    assert srv._tecnologias_en("react native") == {"React Native"}


def test_ruby_on_rails_no_dispara_ruby():
    assert srv._tecnologias_en("ruby on rails") == {"Ruby on Rails"}


def test_dentro_de_una_frase_tampoco():
    encontradas = srv._tecnologias_en("Experiencia con react native en produccion")
    assert encontradas == {"React Native"}


def test_las_tecnologias_de_alrededor_se_siguen_viendo():
    # La correccion no puede dejar de detectar lo demas.
    assert srv._tecnologias_en("react native, Python y AWS") == {"React Native", "Python", "AWS"}


def test_solo_hay_UNA_definicion_de_tecnologias_en():
    # El canario del bug: dos `def _tecnologias_en` en el mismo modulo y la
    # segunda pisa a la primera en silencio. Desde el 28-ago-2026 la funcion vive
    # en `guardrails.py`, asi que se comprueban los dos ficheros: si reapareciera
    # una copia en el servidor, volveria a pisar a la buena via el re-export.
    import guardrails

    for modulo in (guardrails, srv):
        with open(modulo.__file__, encoding="utf-8") as f:
            cuerpo = f.read()
        definiciones = cuerpo.count("\ndef _tecnologias_en(")
        esperadas = 1 if modulo is guardrails else 0
        assert definiciones == esperadas, f"{modulo.__name__}: {definiciones} definiciones"
