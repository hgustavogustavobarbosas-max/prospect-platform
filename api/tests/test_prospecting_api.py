from app.api.deps_clients import (
    get_app_settings,
    get_llm_client,
    get_optional_places_client,
    get_places_client,
)
from app.core.config import get_settings
from app.main import app
from app.services.places import PlaceDTO

P1 = PlaceDTO("pl-1", "Barbearia do Ze", "Rua A, 10", "(11) 91234-5678", None, 4.7, 120, "OPERATIONAL")
P2 = PlaceDTO("pl-2", "Corte Simples", "Rua B, 20", None, "https://corte.example.com", 4.0, 5, "OPERATIONAL")
P3 = PlaceDTO("pl-3", "Studio Bela", "Rua C, 30", "(11) 99876-5432", "https://instagram.com/bela", 4.4, 40, "OPERATIONAL")


class FakePlaces:
    def __init__(self):
        self.pages = {None: ([P1, P2], "tok2"), "tok2": ([P3], None)}
        self.search_calls = 0

    def search_text(self, query, *, page_size=20, page_token=None):
        self.search_calls += 1
        return self.pages[page_token]

    def get_place(self, place_id):
        return {"pl-1": P1, "pl-2": P2, "pl-3": P3}[place_id]


class FakeLLM:
    def adjust(self, features, before_request=None):
        from app.services.ai_scoring import AIAdjustment

        assert "nome" not in features and "telefone" not in features
        if before_request:
            before_request(features)
        return AIAdjustment(5, "perfil promissor", 100)


def setup(settings_kw=None, llm=None):
    fake = FakePlaces()
    cfg = get_settings().model_copy(update={"places_daily_call_limit": 10, **(settings_kw or {})})
    app.dependency_overrides[get_app_settings] = lambda: cfg
    app.dependency_overrides[get_places_client] = lambda: fake
    app.dependency_overrides[get_optional_places_client] = lambda: fake
    app.dependency_overrides[get_llm_client] = lambda: llm
    return fake


BODY = {"segment": "barbearia", "region": "Santana de Parnaiba"}


def test_strict_mode_persists_only_place_id_and_own_analysis(client, svc):
    setup()
    run = client.post("/v1/prospecting/runs", json=BODY, headers=svc).json()
    assert run["status"] == "partial" and run["created"] == 2 and run["pages"] == 1
    biz = client.get("/v1/businesses", headers=svc).json()
    assert len(biz) == 2
    for b in biz:
        assert b["name"].startswith("[Places]") and b["phone"] is None and b["address"] is None
        assert b["website_url"] is None and b["place_id"].startswith("pl-")
    leads = {x["business_id"]: x for x in client.get("/v1/leads", headers=svc).json()}
    tiers = sorted((x["tier"], x["status"]) for x in leads.values())
    assert tiers == [("A", "qualified"), ("C", "new")]
    a = next(x for x in leads.values() if x["tier"] == "A")
    assert a["score_version"] == "v1" and "sem site proprio" in a["justification"]


def test_continue_pagination_then_done_and_dedupe_on_rerun(client, svc):
    setup()
    run = client.post("/v1/prospecting/runs", json=BODY, headers=svc).json()
    done = client.post(f"/v1/prospecting/runs/{run['id']}/continue", json={"max_pages": 1}, headers=svc).json()
    assert done["status"] == "done" and done["created"] == 3 and done["pages"] == 2
    assert client.post(f"/v1/prospecting/runs/{run['id']}/continue", headers=svc).status_code == 409
    again = client.post("/v1/prospecting/runs", json=BODY, headers=svc).json()
    assert again["created"] == 0 and again["duplicates"] == 2


def test_daily_quota_stops_run_without_calling_places(client, svc):
    fake = setup({"places_daily_call_limit": 1})
    first = client.post("/v1/prospecting/runs", json=BODY, headers=svc).json()
    assert first["created"] == 2
    second = client.post("/v1/prospecting/runs", json=BODY, headers=svc).json()
    assert second["status"] == "quota" and second["created"] == 0
    assert fake.search_calls == 1
    usage = client.get("/v1/prospecting/usage", headers=svc).json()
    assert usage[0]["provider"] == "places" and usage[0]["calls"] == 1


def test_permissive_mode_stores_fields_and_purge_clears_them(client, svc, admin):
    setup({"places_storage_mode": "permissive", "places_cache_ttl_days": 0})
    client.post("/v1/prospecting/runs", json=BODY, headers=svc)
    biz = client.get("/v1/businesses", headers=svc).json()
    b1 = next(b for b in biz if b["place_id"] == "pl-1")
    assert b1["name"] == "Barbearia do Ze" and b1["phone_e164"] == "+5511912345678"
    assert client.post("/v1/prospecting/purge-expired", headers=svc).json()["purged"] == 2
    after = client.get(f"/v1/businesses/{b1['id']}", headers=svc).json()
    assert after["name"].startswith("[Places]") and after["phone"] is None and after["place_id"] == "pl-1"


def test_live_details_and_rescore_do_not_persist_contact_data(client, svc):
    setup()
    client.post("/v1/prospecting/runs", json=BODY, headers=svc)
    biz = next(b for b in client.get("/v1/businesses", headers=svc).json() if b["place_id"] == "pl-1")
    live = client.get(f"/v1/prospecting/businesses/{biz['id']}/live", headers=svc).json()
    assert live["phone"] == "(11) 91234-5678" and live["name"] == "Barbearia do Ze"
    assert client.get(f"/v1/businesses/{biz['id']}", headers=svc).json()["phone"] is None
    lead = next(x for x in client.get("/v1/leads", headers=svc).json() if x["business_id"] == biz["id"])
    again = client.post(f"/v1/prospecting/leads/{lead['id']}/score", headers=svc)
    assert again.status_code == 200 and again.json()["tier"] == "A"


def test_suppressed_phone_excludes_lead(client, svc):
    setup()
    client.post("/v1/suppression", json={"identifier": "(11) 91234-5678", "reason": "opt_out"}, headers=svc)
    client.post("/v1/prospecting/runs", json=BODY, headers=svc)
    biz = next(b for b in client.get("/v1/businesses", headers=svc).json() if b["place_id"] == "pl-1")
    lead = next(x for x in client.get("/v1/leads", headers=svc).json() if x["business_id"] == biz["id"])
    assert lead["status"] == "suppressed" and lead["score"] == 0


def test_ai_adjustment_is_applied_and_logged(client, svc):
    setup(llm=FakeLLM())
    client.post("/v1/prospecting/runs", json=BODY, headers=svc)
    leads = client.get("/v1/leads", headers=svc).json()
    boosted = [x for x in leads if x["score_breakdown"].get("ia_ajuste") == 5]
    assert boosted and all("perfil promissor" in x["justification"] for x in boosted)
    usage = {u["provider"]: u for u in client.get("/v1/prospecting/usage", headers=svc).json()}
    assert usage["llm"]["tokens"] >= 100


def test_without_places_key_run_returns_503(client, svc):
    app.dependency_overrides[get_app_settings] = lambda: get_settings().model_copy(
        update={"google_places_api_key": None}
    )
    assert client.post("/v1/prospecting/runs", json=BODY, headers=svc).status_code == 503
