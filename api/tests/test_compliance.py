import pytest

from app.services.compliance import is_optout_message


@pytest.mark.parametrize("msg", ["PARE", "Cancelar", "sair!", "não quero", "Stop"])
def test_optout_detected(msg):
    assert is_optout_message(msg)


@pytest.mark.parametrize(
    "msg", ["quero saber o preço", "pode parar de ligar às 18h e mandar por aqui?", "", None]
)
def test_not_optout(msg):
    assert not is_optout_message(msg)
