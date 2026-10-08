from pathlib import Path
from types import SimpleNamespace as NS

from msw_agent.checker import check_paper, find_citations, parse_references, split_paper, verify_dois

SAMPLE = (Path(__file__).parent / "sample_paper.txt").read_text()


def messages(report, category):
    return [(f.message, f.excerpt) for f in report.findings if f.category == category]


def test_sample_paper_findings():
    r = check_paper(SAMPLE)
    cites = messages(r, "citations")
    refs = messages(r, "references")
    joined = " ".join(m + " " + e for m, e in cites)
    assert "use “&”" in joined and "Smith and Jones, 2020" in joined
    assert "use “and”" in joined and "Adams & Clark" in joined
    assert "et al.” every time" in joined and "Brown, Davis, and Wilson" in joined
    assert "two authors" in joined and "Smith et al. (2020)" in joined
    assert "Kim (2016); check the year" in joined
    assert len(cites) == 5

    never_cited = [e for m, e in refs if "never cited" in m]
    assert len(never_cited) == 2 and any("Zimmer" in e for e in never_cited)
    assert any("https://doi.org" in m for m, _ in refs)
    assert any("Retrieved from" in m for m, _ in refs)
    assert any("alphabetical" in m and "Garcia" in e for m, e in refs)
    assert any("“&” before the last author" in m and "Adams" in e for m, e in refs)
    assert len(refs) == 6

    assert len(messages(r, "quotes")) == 1
    assert {p for p, _, _ in r.ai_phrases} >= {"tapestry", "multifaceted", "it is important to note"}


def test_clean_paper_has_no_findings():
    text = """Intro

Families benefit from services (Doe & Roe, 2019). Ng et al. (2020) agree, noting that
"care must be culturally responsive to every family" (p. 4). The American Psychological
Association (2020) sets the style. Others concur (Ng et al., 2020, p. 5).

References

American Psychological Association. (2020). Publication manual (7th ed.).
Doe, J., & Roe, R. (2019). Services. Social Work, 1(1), 1–2. https://doi.org/10.1000/x
Ng, A., Ou, B., & Pi, C. (2020). Culture. Families in Society, 2(1), 3–4.
"""
    r = check_paper(text)
    assert r.findings == [], r.findings


def test_missing_reference_heading():
    r = check_paper("Some text (Doe, 2019).")
    assert any("No “References” heading" in f.message for f in r.findings)


def test_pdf_wrapped_reference_lines_are_joined():
    refs = parse_references("Doe, J., & Roe, R. (2019). A long title that wraps\nonto a second line. Journal, 1, 2.\nNg, A. (2020). B.")
    assert len(refs) == 2 and "second line" in refs[0].raw


def test_group_and_multi_year_citations():
    cites = find_citations("(National Association of Social Workers [NASW], 2021; Doe, 2019, 2020)")
    assert [(c.names[0], c.year) for c in cites] == [
        ("National Association of Social Workers", "2021"), ("Doe", "2019"), ("Doe", "2020")
    ]


def test_split_uses_last_references_heading():
    body, refs = split_paper("References\nmentioned early\n\nReferences\nDoe, J. (2019). X.\n\nAppendix A\nstuff")
    assert "mentioned early" in body and refs.strip() == "Doe, J. (2019). X."


def test_verify_dois_reports_mismatch():
    refs = parse_references("Doe, J. (2019). X. https://doi.org/10.1000/abc")
    fake = lambda doi: NS(year=2017, authors=["Smith, A."])
    found = verify_dois(refs, fake)
    assert len(found) == 1 and "year is 2017" in found[0].message and "Smith" in found[0].message
