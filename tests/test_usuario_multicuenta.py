"""TDD - un usuario puede recibir ofertas en VARIAS cuentas de correo.

Caso real (28jul2026): a Vero le llegan ofertas a hello.cookyourweb@gmail.com y a
verseper@hotmail.com. Como `buscar_usuario_por_email` filtraba por el campo `Email`
exacto, hubo que crear DOS registros en Notion para que ambos buzones funcionaran.

El parche se rompio solo: los dos registros derivaron. El segundo quedo con el Master
a medias (4.689 chars, sin PERFIL BASE, frente a 8.702 del bueno), sin `Email CV` y
con la ciudad en minusculas. Resultado: el CV de PANEL salio con la cabecera
equivocada, el titular haciendo eco del titulo de la vacante y tecnologias ajenas,
porque el guardrail del titular no tenia PERFIL BASE contra el que validar.

La persona es UNA. Lo que hay son varias direcciones de entrada. El modelo correcto
es un registro con N emails, no N registros.

Campo nuevo en Notion (`Users`): `Emails alias`, rich_text, separados por coma o
salto de linea. `Email` sigue siendo el principal.
"""
import server as srv


def _props(email_principal, alias_texto=None):
    """Simula las properties que devuelve la API de Notion."""
    p = {"Email": {"email": email_principal}}
    if alias_texto is not None:
        p["Emails alias"] = {"rich_text": [{"plain_text": alias_texto}]}
    return p


def test_solo_el_email_principal():
    assert srv.emails_de_usuario(_props("vero@gmail.com")) == {"vero@gmail.com"}


def test_alias_separados_por_coma():
    got = srv.emails_de_usuario(_props("vero@gmail.com", "otra@hotmail.com, tercera@yahoo.es"))
    assert got == {"vero@gmail.com", "otra@hotmail.com", "tercera@yahoo.es"}


def test_alias_separados_por_salto_de_linea():
    got = srv.emails_de_usuario(_props("vero@gmail.com", "otra@hotmail.com\ntercera@yahoo.es"))
    assert got == {"vero@gmail.com", "otra@hotmail.com", "tercera@yahoo.es"}


def test_alias_con_punto_y_coma():
    got = srv.emails_de_usuario(_props("vero@gmail.com", "otra@hotmail.com; tercera@yahoo.es"))
    assert got == {"vero@gmail.com", "otra@hotmail.com", "tercera@yahoo.es"}


def test_normaliza_mayusculas_y_espacios():
    # Un correo escrito a mano en Notion llega con mayusculas o espacios sueltos.
    got = srv.emails_de_usuario(_props("  Vero@Gmail.COM ", " Otra@Hotmail.com "))
    assert got == {"vero@gmail.com", "otra@hotmail.com"}


def test_campo_alias_ausente_no_rompe():
    assert srv.emails_de_usuario({"Email": {"email": "vero@gmail.com"}}) == {"vero@gmail.com"}


def test_alias_vacio_no_aporta_nada():
    assert srv.emails_de_usuario(_props("vero@gmail.com", "   ")) == {"vero@gmail.com"}


def test_separadores_consecutivos_no_crean_vacios():
    got = srv.emails_de_usuario(_props("vero@gmail.com", "otra@hotmail.com,,\n, ;tercera@yahoo.es"))
    assert got == {"vero@gmail.com", "otra@hotmail.com", "tercera@yahoo.es"}


def test_un_email_repetido_no_duplica():
    got = srv.emails_de_usuario(_props("vero@gmail.com", "vero@gmail.com, otra@hotmail.com"))
    assert got == {"vero@gmail.com", "otra@hotmail.com"}


def test_lo_que_no_es_email_se_descarta():
    # Notas sueltas en el campo no deben convertirse en direcciones.
    got = srv.emails_de_usuario(_props("vero@gmail.com", "otra@hotmail.com, (el viejo)"))
    assert got == {"vero@gmail.com", "otra@hotmail.com"}


# ─── coincidencia ───

def test_coincide_con_el_principal():
    assert srv.usuario_tiene_email(_props("vero@gmail.com", "otra@hotmail.com"), "vero@gmail.com")


def test_coincide_con_un_alias():
    assert srv.usuario_tiene_email(_props("vero@gmail.com", "otra@hotmail.com"), "otra@hotmail.com")


def test_la_coincidencia_ignora_mayusculas():
    assert srv.usuario_tiene_email(_props("vero@gmail.com", "Otra@Hotmail.com"), "OTRA@hotmail.COM")


def test_no_coincide_por_subcadena():
    # 'contains' de Notion es de subcadena: 'vero@gmail.com' esta DENTRO de
    # 'notvero@gmail.com'. La verificacion final debe ser exacta o un usuario
    # recibiria el CV de otro.
    assert not srv.usuario_tiene_email(_props("notvero@gmail.com"), "vero@gmail.com")


def test_email_desconocido_no_coincide():
    assert not srv.usuario_tiene_email(_props("vero@gmail.com", "otra@hotmail.com"), "ajeno@x.com")


# ─── el nombre del campo lo escribe una persona en Notion ───

def _props_campo(nombre_campo, texto):
    return {"Email": {"email": "vero@gmail.com"},
            nombre_campo: {"rich_text": [{"plain_text": texto}]}}


def test_acepta_email_alias_en_singular():
    # Caso real 28jul2026: se creo como "Email Alias" y el codigo buscaba
    # "Emails alias". Notion distingue mayusculas y el campo no se encontraba,
    # sin error visible: simplemente no habia alias.
    got = srv.emails_de_usuario(_props_campo("Email Alias", "otra@hotmail.com"))
    assert "otra@hotmail.com" in got


def test_acepta_emails_alias_en_plural():
    got = srv.emails_de_usuario(_props_campo("Emails alias", "otra@hotmail.com"))
    assert "otra@hotmail.com" in got


def test_el_nombre_del_campo_ignora_mayusculas():
    for nombre in ("EMAILS ALIAS", "emails alias", "Emails Alias", "Email alias"):
        got = srv.emails_de_usuario(_props_campo(nombre, "otra@hotmail.com"))
        assert "otra@hotmail.com" in got, f"no reconocio el campo '{nombre}'"


def test_un_campo_que_no_es_de_alias_se_ignora():
    # "Email CV" tambien empieza por Email y NO son direcciones de entrada.
    got = srv.emails_de_usuario({
        "Email": {"email": "vero@gmail.com"},
        "Email CV": {"rich_text": [{"plain_text": "otra@hotmail.com"}]},
    })
    assert got == {"vero@gmail.com"}


# ─── un usuario DESACTIVADO no debe atender ninguna direccion ───

def test_usuario_inactivo_no_responde_a_su_email():
    """Caso real 28jul2026, y costo un CV enviado con la identidad equivocada.

    Habia dos registros de Vero. Se desactivo el duplicado y se anadio su correo
    como alias del bueno. Aun asi el CV siguio saliendo con la cabecera del
    duplicado: `buscar_usuario_por_email` busca primero por `Email` exacto, y el
    duplicado SEGUIA teniendo ese email. Lo encontraba antes de llegar al alias.

    Desactivar tiene que significar 'este registro ya no atiende a nadie'. Si no,
    el desactivado gana siempre al alias del activo.
    """
    props = {"Email": {"email": "vieja@hotmail.com"},
             "Activo": {"checkbox": False}}
    assert not srv.usuario_atiende(props, "vieja@hotmail.com")


def test_usuario_activo_si_responde():
    props = {"Email": {"email": "vero@gmail.com"}, "Activo": {"checkbox": True}}
    assert srv.usuario_atiende(props, "vero@gmail.com")


def test_usuario_activo_responde_por_alias():
    props = {"Email": {"email": "vero@gmail.com"},
             "Activo": {"checkbox": True},
             "Email alias": {"rich_text": [{"plain_text": "vieja@hotmail.com"}]}}
    assert srv.usuario_atiende(props, "vieja@hotmail.com")


def test_sin_campo_activo_se_asume_activo():
    # Compatibilidad: una base sin la columna no debe dejar de funcionar.
    assert srv.usuario_atiende({"Email": {"email": "vero@gmail.com"}}, "vero@gmail.com")


def test_inactivo_tampoco_responde_por_alias():
    props = {"Email": {"email": "vieja@hotmail.com"},
             "Activo": {"checkbox": False},
             "Email alias": {"rich_text": [{"plain_text": "otra@x.com"}]}}
    assert not srv.usuario_atiende(props, "otra@x.com")


# ─── la CONSULTA a Notion tambien tiene que probar los nombres reales ───

def test_hay_varios_nombres_candidatos_para_consultar():
    """Caso real 28jul2026: `emails_de_usuario` se hizo tolerante al nombre del
    campo, pero la CONSULTA a Notion seguia pidiendo 'Emails alias' en plural. La
    propiedad se llamaba 'Email alias'. Notion devolvia 400, la segunda pasada no
    encontraba nada, y /check-email decia que el correo no existia.

    Tolerar el nombre al leer no sirve si al preguntar se usa uno solo.
    """
    cands = srv.campos_alias_candidatos()
    assert "Email alias" in cands
    assert "Emails alias" in cands
    assert cands[0] == srv.CAMPO_EMAILS_ALIAS, "el configurado va primero"


def test_no_hay_candidatos_repetidos():
    cands = srv.campos_alias_candidatos()
    assert len(cands) == len(set(cands))
