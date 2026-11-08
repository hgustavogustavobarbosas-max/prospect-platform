"""Cliente da Google Places API (New): Text Search paginado e Place Details."""

from dataclasses import dataclass

from app.services.retry import retry

BASE_URL = "https://places.googleapis.com/v1"
# Telefone e site entram na faixa de cobranca mais alta (Enterprise): peca so o necessario.
SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
    "places.websiteUri,places.rating,places.userRatingCount,places.businessStatus,nextPageToken"
)
DETAILS_FIELD_MASK = (
    "id,displayName,formattedAddress,nationalPhoneNumber,websiteUri,rating,"
    "userRatingCount,businessStatus"
)


class PlacesError(Exception):
    """Falha da API de Places (mensagem sem segredos)."""


@dataclass(frozen=True)
class PlaceDTO:
    place_id: str
    name: str | None = None
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    rating: float | None = None
    reviews: int | None = None
    business_status: str | None = None


def parse_place(raw: dict) -> PlaceDTO:
    name = (raw.get("displayName") or {}).get("text")
    return PlaceDTO(
        place_id=raw["id"],
        name=name,
        address=raw.get("formattedAddress"),
        phone=raw.get("nationalPhoneNumber"),
        website=raw.get("websiteUri"),
        rating=raw.get("rating"),
        reviews=raw.get("userRatingCount"),
        business_status=raw.get("businessStatus"),
    )


def _transport_errors() -> tuple[type[BaseException], ...]:
    try:
        import httpx

        return (httpx.TransportError,)
    except ImportError:  # ambiente sem httpx (so em testes isolados)
        return (OSError,)


def _retryable(exc: Exception) -> bool:
    return getattr(exc, "retryable", False)


class _Transient(PlacesError):
    retryable = True


class PlacesClient:
    def __init__(self, api_key: str, http=None, timeout: float = 10.0, sleep=None):
        if http is None:
            import httpx

            http = httpx.Client(timeout=timeout)
        self._key = api_key
        self._http = http
        self._sleep = sleep

    def _request(self, method: str, url: str, mask: str, json: dict | None = None) -> dict:
        headers = {"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": mask}

        def call() -> dict:
            try:
                resp = self._http.request(method, url, headers=headers, json=json)
            except _transport_errors() as exc:
                raise _Transient(f"falha de rede: {type(exc).__name__}") from None
            if resp.status_code == 429 or resp.status_code >= 500:
                raise _Transient(f"Places indisponivel ({resp.status_code})")
            if resp.status_code >= 400:
                raise PlacesError(f"Places recusou a requisicao ({resp.status_code})")
            return resp.json()

        kwargs = {"attempts": 3, "base": 0.5, "should_retry": _retryable}
        if self._sleep:
            kwargs["sleep"] = self._sleep
        return retry(call, **kwargs)

    def search_text(
        self, query: str, *, page_size: int = 20, page_token: str | None = None
    ) -> tuple[list[PlaceDTO], str | None]:
        body: dict = {
            "textQuery": query,
            "pageSize": max(1, min(page_size, 20)),
            "languageCode": "pt-BR",
            "regionCode": "BR",
        }
        if page_token:
            body["pageToken"] = page_token  # exige a mesma textQuery e o mesmo field mask
        data = self._request("POST", f"{BASE_URL}/places:searchText", SEARCH_FIELD_MASK, body)
        return [parse_place(p) for p in data.get("places", [])], data.get("nextPageToken")

    def get_place(self, place_id: str) -> PlaceDTO:
        data = self._request("GET", f"{BASE_URL}/places/{place_id}", DETAILS_FIELD_MASK)
        return parse_place(data)
