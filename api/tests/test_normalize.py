from app.services.normalize import (
    dedupe_key,
    normalize_cnpj,
    normalize_identifier,
    normalize_phone_br,
)


def test_phone_formats():
    assert normalize_phone_br("(11) 91234-5678") == "+5511912345678"
    assert normalize_phone_br("+55 11 3456-7890") == "+551134567890"
    assert normalize_phone_br("0055 11 91234 5678") == "+5511912345678"


def test_phone_invalid():
    assert normalize_phone_br("123") is None
    assert normalize_phone_br("(11) 81234-5678") is None  # celular de 9 digitos deve comecar com 9
    assert normalize_phone_br(None) is None


def test_cnpj():
    assert normalize_cnpj("11.222.333/0001-81") == "11222333000181"
    assert normalize_cnpj("11.222.333/0001-82") is None
    assert normalize_cnpj("00000000000000") is None


def test_dedupe_ignores_case_and_accents():
    a = dedupe_key("Barbearia do Zé", "Rua A, 10", None, None)
    b = dedupe_key("BARBEARIA DO ZE", "rua a 10", None, None)
    assert a == b and a is not None


def test_dedupe_priority_cnpj_over_phone():
    assert dedupe_key("x", "y", "+5511912345678", "11222333000181") != dedupe_key(
        "x", "y", "+5511912345678", None
    )


def test_identifier():
    assert normalize_identifier("Foo@Bar.com") == "foo@bar.com"
    assert normalize_identifier("(11) 91234-5678") == "+5511912345678"
    assert normalize_identifier("lixo") is None
