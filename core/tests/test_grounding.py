"""Citation grounding (mimi.grounding): claim splitting, number/name checks, adversarial cases."""

import asyncio
import json
import time

import pytest

from mimi import grounding as g

BURN = ("First aid for a minor burn is to cool it with cool or lukewarm running water for 20 minutes. "
        "Do not use ice, iced water, butter or creams. Remove clothing or jewellery near the burn, "
        "but not anything stuck to the skin. Cover the burn loosely with cling film or a clean plastic bag.")
EVEREST = ("Mount Everest is Earth's highest mountain above sea level, at 8,849 metres. "
           "The first ascent was made on 29 May 1953 by Edmund Hillary and Tenzing Norgay, "
           "members of a British expedition led by John Hunt.")
PARACETAMOL = ("For adults the usual dose of paracetamol is 500 mg to 1 g every four to six hours, "
               "with a maximum of 4 g in 24 hours. Overdose can cause liver failure.")
WATER = "To make water safe by boiling, bring it to a rolling boil for 1 minute. At altitudes above 2,000 metres, boil for 3 minutes."


# --------------------------------------------------------------------- splitting
def test_split_claims_attaches_citations_and_offsets():
    ans = ("Cool the burn under running water for 20 minutes [1]. Don't use ice.[1] "
           "Everest was first climbed in 1953 [2, 3]. It is 8,849 m high [2][3].\n\n"
           "- Cover it with cling film [1]\n- Check e.g. the size of the burn, about 2.5 cm across [1].")
    claims = g.split_claims(ans)
    texts = [c.text for c in claims]
    assert texts[0] == "Cool the burn under running water for 20 minutes."
    assert [c.citations for c in claims] == [[1], [1], [2, 3], [2, 3], [1], [1]]
    for c in claims:  # offsets point at the raw sentence in the original answer
        assert ans[c.start:c.end] == c.raw
    assert "2.5 cm" in texts[-1] and "e.g." in texts[-1]  # no split inside abbreviations or decimals
    assert claims[4].block != claims[5].block  # list items are their own blocks


def test_split_claims_bare_marker_and_markdown():
    ans = "## What to do\n\n**Stop the bleeding** with firm pressure. [2]\n\nWould you like more detail?"
    claims = g.split_claims(ans)
    assert claims[0].text == "What to do" and not claims[0].factual
    assert claims[1].text == "Stop the bleeding with firm pressure." and claims[1].citations == [2]
    assert not claims[-1].factual  # a question


@pytest.mark.parametrize("s,factual", [
    ("I couldn't find that in the offline library.", False),
    ("Let me know if you want the steps.", False),
    ("Hope this helps!", False),
    ("Is it broken?", False),
    ("Here are the steps:", False),
    ("Call 911.", True),
    ("Hillary reached the summit with Norgay.", True),
    ("Apply firm, direct pressure to the wound.", True),
])
def test_is_factual(s, factual):
    assert g.is_factual(s) is factual


# --------------------------------------------------------------------- numbers and names
def test_extract_numbers_units_ranges_words():
    nums = g.extract_numbers("Give 100 to 120 compressions a minute, 5 cm deep; 4,000 mg; 37 °C; twenty-five minutes; 2–3 days")
    got = [(n.value, n.unit) for n in nums]
    assert (100.0, None) in got and (120.0, None) in got
    assert (5.0, "cm") in got and (4000.0, "mg") in got and (37.0, "°c") in got
    assert (25.0, "minutes") in got
    assert (2.0, "days") in got and (3.0, "days") in got  # unit carried back over the range


def test_number_matching_converts_units_but_not_categories():
    assert g.support("The maximum is 4,000 mg a day [1].", PARACETAMOL).verdict == g.SUPPORTED  # 4 g == 4000 mg
    assert g.support("The maximum is 4 ml a day [1].", PARACETAMOL).verdict == g.UNSUPPORTED     # mass vs volume


def test_extract_entities():
    ents = g.extract_entities("It was first climbed by George Mallory and the U.S. Army near Mount Everest. CPR helps.")
    assert "George Mallory" in ents and "Mount Everest" in ents and "CPR" in ents
    assert g.extract_entities("Apply pressure to the wound.") == []  # sentence-initial word isn't a name


# --------------------------------------------------------------------- support: honest answers
@pytest.mark.parametrize("claim,src", [
    ("Hold the burned area under cool running water for about 20 minutes.", BURN),          # paraphrase
    ("Loosely cover the burn with cling film or a clean plastic bag.", BURN),                # reordered
    ("Avoid ice, butter and creams.", BURN),                                                 # negation agrees
    ("Edmund Hillary and Tenzing Norgay first reached the summit of Everest in 1953.", EVEREST),
    ("Everest stands 8,849 metres above sea level.", EVEREST),
    ("Adults can take 500 mg to 1 g of paracetamol every 4 to 6 hours.", PARACETAMOL),       # number words vs digits
    ("Above 2,000 metres, boil the water for 3 minutes.", WATER),
])
def test_supported_paraphrases(claim, src):
    r = g.support(claim, src)
    assert r.verdict == g.SUPPORTED, (claim, r)


def test_cool_water_not_ice_is_not_a_contradiction():
    # the source's "not ice" negates ice, not the cooling the claim asserts
    src = "Cool the burn with cool running water, not ice, for 20 minutes."
    r = g.support("Cool the burn with cool running water for 20 minutes.", src)
    assert r.verdict == g.SUPPORTED and not r.polarity_mismatch


# --------------------------------------------------------------------- support: adversarial
def test_invented_number_is_unsupported():
    r = g.support("The first ascent of Everest was in 1975.", EVEREST)
    assert r.verdict == g.UNSUPPORTED and r.missing_numbers == ["1975"]


def test_changed_dose_is_unsupported_even_with_full_word_overlap():
    r = g.support("For adults the usual dose of paracetamol is 1500 mg every four to six hours.", PARACETAMOL)
    assert r.verdict == g.UNSUPPORTED
    assert any("1500" in x for x in r.missing_numbers)
    assert r.lexical > 0.8  # the words all match; only the number check catches it


def test_changed_duration_is_flagged():
    r = g.support("Cool the burn under running water for 45 minutes.", BURN)
    assert r.verdict == g.UNSUPPORTED and r.missing_numbers


def test_swapped_name_is_not_supported():
    r = g.support("The first ascent was made in 1953 by George Mallory.", EVEREST)
    assert r.verdict != g.SUPPORTED and "George Mallory" in r.missing_entities
    r2 = g.support("The expedition that made the first ascent was led by Chris Bonington.", EVEREST)
    assert r2.verdict != g.SUPPORTED and r2.missing_entities


def test_contradiction_by_negation():
    r = g.support("Put butter on the burn.", BURN)
    assert r.verdict == g.UNSUPPORTED and r.polarity_mismatch
    r2 = g.support("Do not cool the burn with running water.", BURN)
    assert r2.verdict == g.UNSUPPORTED and r2.polarity_mismatch
    # the source's exception ("but not anything stuck to the skin") is contradicted …
    r3 = g.support("Remove clothing stuck to the skin.", BURN)
    assert r3.verdict == g.UNSUPPORTED and r3.polarity_mismatch
    # … while the part it allows is fine
    assert g.support("Remove clothing and jewellery near the burn.", BURN).verdict == g.SUPPORTED


def test_wrong_source_and_better_source():
    ans = "Cool the burn with running water for 20 minutes [2]. Hillary and Norgay summited in 1953 [2]."
    r = g.check_answer(ans, {1: BURN, 2: EVEREST})
    first, second = r.claims
    assert first.verdict == g.UNSUPPORTED and first.checks[0].better_source == 1
    assert second.verdict == g.SUPPORTED


def test_out_of_range_citation_is_invalid():
    r = g.check_answer("Cool the burn for 20 minutes [7].", {1: BURN})
    assert r.claims[0].checks[0].verdict == g.INVALID
    assert r.flags()[0]["reasons"] == ["citation points to no source"]


# --------------------------------------------------------------------- whole-answer report
def test_report_counts_faithfulness_and_flags():
    ans = ("Cool a burn under cool running water for 20 minutes [1]. Do not use ice or butter [1]. "
           "Everest was first climbed in 1975 [2].\n\n"
           "Burns heal faster with honey.\n\nI hope this helps!")
    r = g.check_answer(ans, {1: BURN, 2: EVEREST})
    s = r.summary()
    assert s["citations"] == 3 and s["supported"] == 2 and s["unsupported"] == 1
    assert s["factual_sentences"] == 4 and s["uncited_factual"] == 1
    assert [c.text for c in r.uncited_factual] == ["Burns heal faster with honey."]
    assert r.faithfulness == pytest.approx(2 / 4, abs=1e-3)
    assert r.citation_precision == pytest.approx(2 / 3, abs=1e-3)
    assert r.coverage == pytest.approx(3 / 4, abs=1e-3)
    flags = r.flags()
    assert len(flags) == 1 and flags[0]["n"] == 2 and "1975" in flags[0]["reasons"][0]
    assert ans[flags[0]["start"]:flags[0]["end"]].startswith("Everest was first climbed in 1975")
    json.dumps(r.to_dict())  # serialisable for message meta / results files


def test_paragraph_level_citation_covers_uncited_sentence():
    ans = "Run cool water over the burn. Keep it under the water for 20 minutes [1]."
    r = g.check_answer(ans, {1: BURN})
    assert r.claims[0].covered_by == [1]
    assert r.uncited_factual == [] and r.coverage == 1.0


def test_no_sources_means_everything_factual_is_uncited():
    r = g.check_answer("Hillary and Norgay climbed Everest in 1953.", {})
    assert r.faithfulness == 0.0 and len(r.uncited_factual) == 1


def test_non_factual_answer_has_no_score():
    r = g.check_answer("I couldn't find that in the offline library. Would you like me to try another search?", {1: BURN})
    assert r.faithfulness is None and r.citation_precision is None


@pytest.mark.parametrize("sources", [
    {1: BURN},
    [BURN],
    [{"n": 1, "title": "Burn", "text": BURN}],
    [{"n": 1, "title": "Burn", "snippet": BURN[:240]}],
])
def test_source_shapes(sources):
    r = g.check_answer("Cool the burn with running water for 20 minutes [1].", sources)
    assert r.claims[0].verdict == g.SUPPORTED


# --------------------------------------------------------------------- embedding hook
def _fake_embed(texts):
    # same topic -> same direction; a crude stand-in for bge-m3
    return [[1.0, 0.0] if ("wound" in t.lower() or "bleed" in t.lower()) else [0.0, 1.0] for t in texts]


def test_embedding_rescues_paraphrase_but_not_invented_numbers():
    src = "Apply firm direct pressure on the bleeding site with a clean cloth."
    claim = "Press hard on the wound to stop it bleeding [1]."
    lexical = g.check_answer(claim, {1: src})
    assert lexical.claims[0].verdict != g.SUPPORTED  # few shared words
    calls = []

    def embed(texts):
        calls.append(len(texts))
        return _fake_embed(texts)

    with_emb = g.check_answer(claim, {1: src}, embed=embed)
    assert calls == [2]  # one batched call
    assert with_emb.claims[0].verdict in (g.SUPPORTED, g.WEAK)
    assert with_emb.claims[0].checks[0].score > lexical.claims[0].checks[0].score
    invented = g.check_answer("Press hard on the wound for 45 minutes to stop it bleeding [1].", {1: src}, embed=_fake_embed)
    assert invented.claims[0].verdict == g.UNSUPPORTED


def test_async_embedder_and_failure_fallback():
    async def ok(texts):
        return _fake_embed(texts)

    async def broken(texts):
        raise RuntimeError("embedding server down")

    claim = "Press hard on the wound to stop it bleeding [1]."
    src = {1: "Apply firm direct pressure on the bleeding site with a clean cloth."}
    a = asyncio.run(g.check_answer_async(claim, src, embed=ok))
    b = asyncio.run(g.check_answer_async(claim, src, embed=broken))
    assert a.claims[0].checks[0].embedding is not None
    assert b.claims[0].checks[0].embedding is None  # lexical report, no exception


def test_fast_on_long_sources():
    long = " ".join(f"Paragraph {i} discusses burns, cooling water, dressings and infection risk." for i in range(600))
    ans = " ".join(f"Cool the burn with water for {i} minutes [1]." for i in range(12))
    t0 = time.perf_counter()
    g.check_answer(ans, {1: long, 2: long})
    assert time.perf_counter() - t0 < 2.0
