"""Rule-based APA 7 checks and an AI-style phrase scan. No API key needed.

These are heuristics over plain text: they catch common, mechanical mistakes
(missing references, '&' vs 'and', et al., page numbers for quotes, reference
order, DOI format). They can't see italics or hanging indents, and unusual
citations (secondary sources, legal citations, personal communications) may be
reported as unmatched. Every finding is phrased as "check this", not a verdict.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

YEAR = r"(?:\d{4}[a-z]?|n\.d\.)"
NAME = r"[A-Z][\w'’\-]+"


@dataclass
class Finding:
    category: str  # "citations", "references", "quotes", "style"
    message: str
    excerpt: str = ""


@dataclass
class Reference:
    raw: str
    authors_text: str
    surnames: list[str]
    year: str | None
    doi: str | None

    @property
    def first(self) -> str:
        return self.surnames[0] if self.surnames else self.authors_text


@dataclass
class Citation:
    raw: str
    names: list[str]  # surnames or group name, in order
    et_al: bool
    year: str
    narrative: bool
    joiner: str | None  # "&", "and" or None
    before: str = ""  # text just before a narrative citation, to recognize group authors


@dataclass
class Report:
    word_count: int
    references: list[Reference]
    citations: list[Citation]
    findings: list[Finding] = field(default_factory=list)
    ai_phrases: list[tuple[str, int, str]] = field(default_factory=list)  # (phrase, count, example)
    has_reference_section: bool = True

    def by_category(self, category: str) -> list[Finding]:
        return [f for f in self.findings if f.category == category]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


def _snip(text: str, start: int, end: int, pad: int = 40) -> str:
    a, b = max(0, start - pad), min(len(text), end + pad)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


# ---------------------------------------------------------------------------
# Splitting the paper
# ---------------------------------------------------------------------------

REF_HEADING = re.compile(r"^\s*(references|reference list|works cited|bibliography)\s*:?\s*$", re.I | re.M)
APPENDIX_HEADING = re.compile(r"^\s*appendix\b.*$", re.I | re.M)


def split_paper(text: str) -> tuple[str, str | None]:
    """Returns (body, reference_section). Uses the last 'References' heading."""
    matches = list(REF_HEADING.finditer(text))
    if not matches:
        return text, None
    m = matches[-1]
    body, refs = text[: m.start()], text[m.end():]
    app = APPENDIX_HEADING.search(refs)
    if app:
        refs = refs[: app.start()]
    return body, refs


# ---------------------------------------------------------------------------
# Reference list
# ---------------------------------------------------------------------------

_ENTRY_START = re.compile(rf"^[A-Z][^\n]{{0,300}}?\(({YEAR})[^)]*\)")
_SURNAME = re.compile(rf"({NAME}(?:[ -](?:{NAME}|van|von|de|der|del|da|la|le))*),\s+(?:[A-Z]\.[\s-]?)+")
_DOI = re.compile(r"10\.\d{4,9}/[^\s]+")


def parse_references(section: str) -> list[Reference]:
    entries: list[str] = []
    for line in section.splitlines():
        line = line.strip()
        if not line:
            continue
        if _ENTRY_START.match(line) or not entries:
            entries.append(line)
        else:  # wrapped line from a PDF
            entries[-1] += " " + line
    refs = []
    for e in entries:
        m = re.search(rf"\(({YEAR})[^)]*\)", e)
        authors_text = e[: m.start()].strip() if m else ""
        surnames = _SURNAME.findall(authors_text)
        if not surnames and authors_text:
            surnames = [authors_text.rstrip(" .")]  # group author
        doi = _DOI.search(e)
        refs.append(
            Reference(
                raw=e,
                authors_text=authors_text,
                surnames=surnames,
                year=m.group(1) if m else None,
                doi=doi.group(0).rstrip(".") if doi else None,
            )
        )
    return refs


# ---------------------------------------------------------------------------
# In-text citations
# ---------------------------------------------------------------------------

_PAREN = re.compile(r"\(([^()]*?\d{4}[a-z]?[^()]*?|[^()]*?n\.d\.[^()]*?)\)")
_SEGMENT = re.compile(
    rf"^(?:e\.g\.,?\s*|i\.e\.,?\s*|see\s+(?:also\s+)?|cf\.\s*|as cited in\s+)?"
    rf"(?P<authors>[A-Z].*?),\s*(?P<years>{YEAR}(?:,\s*{YEAR})*)(?P<rest>.*)$"
)
_NARRATIVE = re.compile(
    rf"(?P<authors>{NAME}(?:,\s{NAME})*(?:,?\s(?:and|&)\s{NAME})?(?:\set al\.)?)\s\((?P<year>{YEAR})(?P<rest>[^)]*)\)"
)
_NOT_NAMES = {
    "In", "The", "This", "That", "These", "Those", "Since", "During", "By", "From", "Until",
    "Before", "After", "Between", "Spring", "Summer", "Fall", "Autumn", "Winter",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
}


def _split_names(authors: str) -> tuple[list[str], bool, str | None]:
    authors = re.sub(r"\s*\[[^\]]*\]", "", authors).strip()  # drop "[NASW]"
    et_al = bool(re.search(r"\bet al\.?", authors))
    authors = re.sub(r",?\s*et al\.?", "", authors)
    joiner = "&" if "&" in authors else ("and" if re.search(r"\band\b", authors) else None)
    parts = [p.strip() for p in re.split(r",?\s+(?:&|and)\s+|,\s*", authors) if p.strip()]
    # A group author like "National Association of Social Workers" contains "of"/"and"
    # inside the name; if splitting produced lowercase fragments, keep it whole.
    if any(not p[0].isupper() for p in parts):
        return [authors], et_al, None
    return parts, et_al, joiner


def find_citations(body: str) -> list[Citation]:
    flat = re.sub(r"\s+", " ", body)
    cites: list[Citation] = []
    for m in _PAREN.finditer(flat):
        for seg in m.group(1).split(";"):
            sm = _SEGMENT.match(seg.strip())
            if not sm:
                continue
            names, et_al, joiner = _split_names(sm.group("authors"))
            for y in re.findall(YEAR, sm.group("years")):
                cites.append(Citation(seg.strip(), names, et_al, y, False, joiner))
    for m in _NARRATIVE.finditer(flat):
        names, et_al, joiner = _split_names(m.group("authors"))
        if names[0] in _NOT_NAMES:
            continue
        before = flat[max(0, m.start() - 100): m.start()]
        cites.append(Citation(m.group(0), names, et_al, m.group("year"), True, joiner, before))
    return cites


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _matches(c: Citation, r: Reference) -> bool:
    if r.year is None or c.year.rstrip("abcdefghij") != r.year.rstrip("abcdefghij"):
        return False
    if c.year != r.year and c.year[-1].isalpha() and r.year[-1].isalpha():
        return False  # 2020a vs 2020b
    first = _norm(c.names[0])
    if first and (first == _norm(r.first) or _norm(r.authors_text).startswith(first)):
        return True
    # Narrative group author: "the National Association of Social Workers (2021)"
    # is matched as "Workers"; check whether the full group name precedes it.
    group = _norm(r.authors_text)
    return c.narrative and len(r.surnames) == 1 and len(group) > len(first) and (
        _norm(c.before + c.names[0]).endswith(group)
    )


def _check_citations(citations: list[Citation], refs: list[Reference], findings: list[Finding]) -> None:
    seen: set[str] = set()
    for c in citations:
        key = f"{_norm(c.names[0])}|{c.year}|{c.narrative}|{c.joiner}|{len(c.names)}|{c.et_al}"
        if key in seen:
            continue
        seen.add(key)

        if not c.narrative and c.joiner == "and":
            findings.append(Finding("citations", "Inside parentheses, use “&” between author names, not “and”.", c.raw))
        if c.narrative and c.joiner == "&":
            findings.append(Finding("citations", "In running text, use “and” between author names, not “&”.", c.raw))
        if len(c.names) >= 3 and not c.et_al:
            findings.append(
                Finding("citations", "APA 7: with three or more authors, cite only the first author plus “et al.” every time.", c.raw)
            )

        match = next((r for r in refs if _matches(c, r)), None)
        if refs and match is None:
            same_name = [r for r in refs if _norm(r.first) == _norm(c.names[0])]
            hint = f" The reference list has {c.names[0]} ({same_name[0].year}); check the year." if same_name else ""
            findings.append(Finding("citations", f"Cited in the text but not found in the reference list.{hint}", c.raw))
        elif match is not None:
            n_ref = len(match.surnames)
            if c.et_al and n_ref == 2:
                findings.append(Finding("citations", "This work has two authors; name both instead of using “et al.”.", c.raw))
            if not c.et_al and n_ref >= 3 and len(c.names) == 2:
                findings.append(Finding("citations", "This work has three or more authors; use “et al.” after the first author.", c.raw))


def _check_references(citations: list[Citation], refs: list[Reference], findings: list[Finding]) -> None:
    for r in refs:
        if r.year is None:
            findings.append(Finding("references", "Couldn't find a year in parentheses, e.g. “(2020).” or “(n.d.).”", r.raw[:160]))
            continue
        if not any(_matches(c, r) for c in citations):
            findings.append(Finding("references", "In the reference list but never cited in the text.", r.raw[:160]))
        if len(r.surnames) >= 2 and "&" not in r.authors_text:
            findings.append(Finding("references", "Put “&” before the last author's name in a reference.", r.raw[:160]))
        if re.search(r"\bdoi:\s*10\.|dx\.doi\.org|http://doi\.org", r.raw, re.I):
            findings.append(Finding("references", "APA 7 formats DOIs as links: https://doi.org/10.xxxx/…", r.raw[:160]))
        if re.search(r"\bretrieved from\b", r.raw, re.I) and not re.search(r"\bretrieved \w+ \d", r.raw, re.I):
            findings.append(Finding("references", "APA 7 dropped “Retrieved from”; just give the URL.", r.raw[:160]))

    keys = [_norm(r.authors_text or r.raw) for r in refs]
    for i in range(1, len(keys)):
        if keys[i] < keys[i - 1]:
            findings.append(
                Finding("references", "The reference list isn't in alphabetical order by first author's surname here.", refs[i].raw[:160])
            )
            break


_QUOTE = re.compile(r"[“\"]([^”\"]{20,}?)[”\"]")


def _check_quotes(body: str, findings: list[Finding]) -> None:
    flat = re.sub(r"\s+", " ", body)
    for m in _QUOTE.finditer(flat):
        if len(m.group(1).split()) < 5:
            continue
        after = flat[m.end(): m.end() + 120]
        before = flat[max(0, m.start() - 120): m.start()]
        cite = re.match(r"\s*\(([^)]*)\)", after)
        has_page = lambda s: re.search(r"\b(p|pp|para|paras)\.\s*\d|\bSection\b|\bslide\b", s, re.I)
        if cite and has_page(cite.group(1)):
            continue
        if not cite and re.search(r"\(\d{4}[a-z]?\)", before) and re.match(r"\s*\((p|pp|para)\.", after):
            continue
        findings.append(
            Finding("quotes", "Direct quotation without a page or paragraph number (e.g., p. 12 or para. 3).", _snip(flat, m.start(), m.end(), 10))
        )


# Phrases that show up far more often in AI-generated academic text than in
# student writing. Their presence proves nothing; it's a style flag.
AI_PHRASES = [
    "delve", "delves", "delving", "tapestry", "multifaceted", "it is important to note",
    "it's important to note", "it is worth noting", "plays a crucial role", "plays a pivotal role",
    "in today's fast-paced", "in today's world", "ever-evolving", "navigate the complexities",
    "navigating the complexities", "a testament to", "underscores the importance",
    "highlights the importance", "fostering a sense", "holistic approach", "nuanced understanding", "intricate",
    "pivotal", "paramount", "realm", "landscape of", "shed light on", "sheds light on",
    "serves as a reminder", "embark", "seamlessly", "harness the power",
]


def scan_ai_phrases(body: str) -> list[tuple[str, int, str]]:
    flat = re.sub(r"\s+", " ", body)
    low = flat.lower()
    out = []
    for phrase in AI_PHRASES:
        hits = [m.start() for m in re.finditer(r"(?<![a-z])" + re.escape(phrase), low)]
        if hits:
            out.append((phrase, len(hits), _snip(flat, hits[0], hits[0] + len(phrase))))
    return sorted(out, key=lambda x: -x[1])


def check_paper(text: str) -> Report:
    body, ref_section = split_paper(text)
    refs = parse_references(ref_section) if ref_section else []
    citations = find_citations(body)
    report = Report(
        word_count=len(re.findall(r"\b[\w'’-]+\b", body)),
        references=refs,
        citations=citations,
        has_reference_section=ref_section is not None,
    )
    if ref_section is None:
        report.findings.append(
            Finding("references", "No “References” heading found, so citations couldn't be matched to a reference list.")
        )
    _check_citations(citations, refs, report.findings)
    if refs:
        _check_references(citations, refs, report.findings)
    _check_quotes(body, report.findings)
    report.ai_phrases = scan_ai_phrases(body)
    return report


def verify_dois(refs: list[Reference], fetch) -> list[Finding]:
    """Look up each DOI (fetch = tools.fetch_crossref) and compare author and year."""
    findings = []
    for r in refs:
        if not r.doi:
            continue
        try:
            work = fetch(r.doi)
        except Exception as e:  # ToolError or network problems
            findings.append(Finding("references", f"DOI could not be verified: {e}", r.raw[:160]))
            continue
        problems = []
        if work.year and r.year and str(work.year) != r.year.rstrip("abcdefghij"):
            problems.append(f"year is {work.year} in Crossref")
        crossref_first = work.authors[0].split(",")[0] if work.authors else ""
        if crossref_first and _norm(crossref_first) != _norm(r.first):
            problems.append(f"first author is {crossref_first} in Crossref")
        if problems:
            findings.append(Finding("references", "DOI doesn't match this reference: " + "; ".join(problems) + ".", r.raw[:160]))
    return findings


def report_markdown(report: Report, extra: list[Finding] | None = None) -> str:
    """The report as Markdown, for showing in the app or saving."""
    findings = report.findings + (extra or [])
    lines = [
        f"**Words (excluding references):** {report.word_count:,} · "
        f"**In-text citations found:** {len(report.citations)} · **References:** {len(report.references)}",
        "",
    ]
    titles = {
        "citations": "In-text citations",
        "references": "Reference list",
        "quotes": "Quotations",
    }
    for cat, title in titles.items():
        items = [f for f in findings if f.category == cat]
        lines.append(f"### {title} ({len(items)} to check)")
        if not items:
            lines.append("No problems found by the automatic checks.")
        for f in items:
            lines.append(f"- {f.message}" + (f"  \n  `{f.excerpt}`" if f.excerpt else ""))
        lines.append("")
    lines.append("### Phrases often associated with AI-generated writing")
    if report.ai_phrases:
        lines.append(
            "These are style flags, not evidence. Plenty of human writers use them, and their absence "
            "doesn't mean a paper will pass an AI detector. Consider rewording the ones that sound generic."
        )
        for phrase, n, ex in report.ai_phrases:
            lines.append(f"- “{phrase}” ×{n}  \n  `{ex}`")
    else:
        lines.append("None of the listed phrases appear.")
    return "\n".join(lines)
