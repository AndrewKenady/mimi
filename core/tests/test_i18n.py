"""Core's own words in Spanish and French, and the safety checks that must not depend on English."""

import re

import pytest

from mimi import grounding, i18n
from mimi.chat import looks_factual
from mimi.i18n_messages import MESSAGES


@pytest.fixture()
def es():
    token = i18n.use("es")
    yield
    i18n._current.reset(token)


def test_messages_and_rendered_text_are_translated(es):
    assert i18n.tr("Thinking…") == "Pensando…"
    assert i18n.tr("Waking up {name}…", name="Gemma 4 12B") == "Despertando a Gemma 4 12B…"
    # text Core already wrote in English: placeholders keep the user's words, "where" is translated
    assert i18n.localize("Searched the library for “hipotermia”") == "Buscó “hipotermia” en la biblioteca"
    assert i18n.localize("Too many wrong PINs. Try again in 12 seconds.") == "Demasiados PIN incorrectos. Vuelve a intentarlo en 12 segundos."
    assert i18n.localize("Its start page needs JavaScript, and Mimi couldn't read its list of talks.") == \
        "Su página de inicio necesita JavaScript, y Mimi no pudo leer su lista de charlas."
    assert i18n.localize("Some text no one translated") == "Some text no one translated"
    assert i18n.join(["WikiMed", "Wikipedia"]) == "WikiMed y Wikipedia"


def test_english_and_unknown_locales_change_nothing():
    for header in (None, "", "en-US", "de", "xx"):
        token = i18n.use(header)
        try:
            assert i18n.current() == "en"
            assert i18n.tr("Thinking…") == "Thinking…"
            assert i18n.localize("Wrong PIN.") == "Wrong PIN."
        finally:
            i18n._current.reset(token)
    assert i18n.normalize("fr-CA") == "fr" and i18n.normalize("ES") == "es"


@pytest.mark.parametrize("locale", sorted(MESSAGES))
def test_every_translation_keeps_its_placeholders(locale):
    for en, translated in MESSAGES[locale].items():
        assert set(re.findall(r"\{(\w+)\}", en)) == set(re.findall(r"\{(\w+)\}", translated)), (locale, en)


def test_language_detection():
    assert i18n.detect("¿Cómo trato la hipotermia en la montaña?") == "es"
    assert i18n.detect("Comment traiter une hypothermie quand on est en montagne ?") == "fr"
    assert i18n.detect("How do I treat hypothermia on a mountain?") == "en"
    assert i18n.detect("Calienta a la persona poco a poco y dale bebidas tibias.") == "es"
    assert i18n.detect("OK") is None and i18n.detect("") is None


@pytest.mark.parametrize("text", [
    "¿Cómo trato la hipotermia?", "Explícame cómo purificar agua con cloro", "Dime cuánto dura la rabia sin tratamiento",
    "Comment purifier l'eau avec de l'eau de Javel ?", "Dites-moi combien de temps faire bouillir l'eau", "Pourquoi le ciel est bleu",
])
def test_questions_in_spanish_and_french_are_grounded(text):
    # D7: factual questions must search the library first, whatever language they're asked in
    assert looks_factual(text)


@pytest.mark.parametrize("text", ["hola", "¡Gracias!", "bonjour", "Merci beaucoup", "Escribe un poema sobre el mar", "Traduis ceci en anglais"])
def test_chitchat_and_creative_requests_in_spanish_and_french_are_not(text):
    assert not looks_factual(text)


SOURCE = {1: "Hypothermia is a core temperature below 35.0 °C. Everest stands 8,849 metres above sea level. Boil water for 1 minute."}


def test_numbers_are_checked_across_languages():
    ok = "La hipotermia empieza por debajo de 35,0 °C [1]. El Everest mide 8.849 metros [1]. Hierve el agua 1 minuto [1]."
    assert grounding.number_flags(ok, SOURCE) == []
    bad = "Hierve el agua durante 10 minutos [1]. La hipotermia empieza por debajo de 35 °C [1]."
    flags = grounding.number_flags(bad, SOURCE)
    assert [(f["n"], f["verdict"], f["reasons"]) for f in flags] == [(1, "unsupported", ["number not in source: 10"])]
    assert flags[0]["sentence"].startswith("Hierve el agua durante 10 minutos")


def test_cross_language_check_flags_citations_to_nothing_and_respects_a_better_citation():
    assert grounding.number_flags("Hiérvela un minuto [3].", SOURCE)[0]["verdict"] == "invalid"
    two = {1: "Boil water for 1 minute.", 2: "At altitude, boil it for 3 minutes."}
    assert grounding.number_flags("En altura, hiérvela 3 minutos [1][2].", two) == []


def test_api_errors_arrive_in_the_interface_language(client):
    client.post("/api/auth/setup", json={"name": "Ada"})
    r = client.post("/api/auth/setup", json={"name": "Bea"}, headers={"x-mimi-locale": "es"})
    assert r.status_code == 409 and r.json()["detail"] == "Mimi ya está configurado."
    r = client.post("/api/auth/setup", json={"name": "Bea"}, headers={"x-mimi-locale": "fr"})
    assert r.json()["detail"] == "Mimi est déjà configuré."
    assert client.post("/api/auth/setup", json={"name": "Bea"}).json()["detail"] == "Mimi is already set up."
