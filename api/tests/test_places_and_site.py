from app.services.places import DETAILS_FIELD_MASK, SEARCH_FIELD_MASK, PlacesClient, PlacesError, parse_place
from app.services.retry import retry
from app.services.site_check import classify_url, is_public_host

RAW = {
    "id": "ChIJabc",
    "displayName": {"text": "Barbearia do Zé", "languageCode": "pt-BR"},
    "formattedAddress": "Rua A, 10",
    "nationalPhoneNumber": "(11) 91234-5678",
    "websiteUri": "https://instagram.com/barbeariadoze",
    "rating": 4.7,
    "userRatingCount": 120,
    "businessStatus": "OPERATIONAL",
}


def test_parse_place():
    p = parse_place(RAW)
    assert p.place_id == "ChIJabc" and p.name == "Barbearia do Zé" and p.reviews == 120
    assert parse_place({"id": "x"}).name is None


def test_field_masks_request_page_token_and_ids():
    assert "nextPageToken" in SEARCH_FIELD_MASK and "places.id" in SEARCH_FIELD_MASK
    assert not DETAILS_FIELD_MASK.startswith("places.")


def test_classify_url():
    assert classify_url(None) == "none" and classify_url("  ") == "none"
    assert classify_url("https://www.instagram.com/x") == "social"
    assert classify_url("linktr.ee/x") == "social"
    assert classify_url("https://barbeariadoze.com.br") == "site"
    assert classify_url("https://notinstagram.com") == "site"  # nao confunde sufixo parcial


def test_ssrf_guard_rejects_internal_hosts():
    for host in ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "localhost", ""]:
        assert is_public_host(host) is False, host
    assert is_public_host("8.8.8.8") is True


def test_retry_backoff_and_give_up():
    calls, sleeps = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("falha")
        return "ok"

    assert retry(flaky, attempts=3, sleep=sleeps.append, rng=lambda: 0.0) == "ok"
    assert len(calls) == 3 and sleeps == [0.25, 0.5]  # 0.5*2^i * (0.5 + 0)

    n = []

    def always():
        n.append(1)
        raise ValueError("x")

    try:
        retry(always, attempts=2, sleep=lambda s: None)
    except ValueError:
        assert len(n) == 2
    else:
        raise AssertionError("deveria propagar")

    m = []

    def fatal():
        m.append(1)
        raise KeyError("nao repetir")

    try:
        retry(fatal, attempts=5, should_retry=lambda e: False, sleep=lambda s: None)
    except KeyError:
        assert len(m) == 1


class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body or {}

    def json(self):
        return self._b


class _Http:
    def __init__(self, codes):
        self.codes, self.n = codes, 0

    def request(self, method, url, headers=None, json=None):
        code = self.codes[min(self.n, len(self.codes) - 1)]
        self.n += 1
        return _Resp(code, {"places": [RAW], "nextPageToken": "tok"})


def test_client_retries_5xx_but_not_4xx():
    ok = PlacesClient("k", http=_Http([503, 429, 200]), sleep=lambda s: None)
    places, token = ok.search_text("barbearia em sp")
    assert len(places) == 1 and token == "tok"
    bad = PlacesClient("k", http=_Http([403]), sleep=lambda s: None)
    try:
        bad.search_text("x")
    except PlacesError as e:
        assert "403" in str(e) and "k" != str(e)
    else:
        raise AssertionError("deveria falhar")
    assert bad._http.n == 1  # 4xx nao repete
