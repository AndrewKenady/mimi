"""search_library finds articles with the model's words and picks their paragraphs with the user's question too."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from mimi import tools
from mimi.auth import Ctx
from mimi.kiwix import Hit, Passage


class RecordingKiwix:
    def __init__(self):
        self.searched, self.picked = [], []

    async def search(self, q, collections=None, limit=5, books=None, local=None):
        self.searched.append(q)
        return [Hit(title="Water Treatment, p. 23", path="files/Water.pdf", book="water", book_title="Water Treatment Library",
                    collection="survival", snippet="")]

    async def passage(self, hit, q, chars):
        self.picked.append(q)
        return Passage(title=hit.title, book=hit.book, book_title=hit.book_title, collection=hit.collection, path=hit.path,
                       text="FEMA recommends adding 16 drops (1/8 teaspoon) of household bleach to each gallon of drinking water.",
                       url="/library/read/water/files/Water.pdf")


def _run(question: str, args: str) -> RecordingKiwix:
    kiwix = RecordingKiwix()
    dev = {"tools": SimpleNamespace(disabled=[], plugins=[]),
           "knowledge": SimpleNamespace(articles_per_search=3, snippet_chars=900),
           "general": SimpleNamespace(units="metric")}
    svc = SimpleNamespace(settings=SimpleNamespace(device=lambda k: dev[k]), kiwix=kiwix,
                          kiwix_service=SimpleNamespace(alive=lambda: True))
    st = tools.TurnState(ctx=Ctx({"id": "u1", "name": "Ada", "role": "owner"}, None, True), chat_id="c", message_id="m",
                         query=question, mode={}, vision=False)
    res = asyncio.run(tools.run("search_library", args, st, svc))
    assert res.ok
    return kiwix


def test_paragraphs_are_picked_with_the_users_question_as_well():
    question = "How much unscented household bleach should I add to a gallon of water to disinfect it?"
    k = _run(question, '{"query": "disinfect water with bleach ratio"}')
    assert k.searched == ["disinfect water with bleach ratio"]  # finding the article is unchanged
    assert k.picked == [f"disinfect water with bleach ratio {question}"]


def test_a_query_that_already_holds_the_question_is_used_as_is():
    k = _run("purify water", '{"query": "how to purify water"}')
    assert k.picked == ["how to purify water"]
