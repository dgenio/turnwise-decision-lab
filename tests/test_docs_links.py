"""Every link the repository's own pages make must resolve, offline (#23).

Checks each Markdown file and each committed HTML page:

* relative links (``docs/x.md``, ``../AGENTS.md``, ``index.html``) point to a file or directory that exists
  in this checkout and does not leave the repository;
* ``#anchors`` on Markdown targets (same file or another file) match a heading, using GitHub's slug rules,
  or an explicit ``<a name>``/``<a id>``;
* links to this repository's ``blob/main`` and ``tree/main`` paths on github.com name a path that exists.

Not checked, deliberately: other external URLs (issues, PRs, Actions runs, archived commit SHAs, other sites).
They cannot be verified without the network, and CI runs offline. Archived recovery commits are pinned as full
SHAs by ``tests/test_repository_integrity.py``. Links inside fenced code blocks and code spans are not links.
Stdlib only.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules"}

_REPO_URL = re.compile(r"^https://github\.com/dgenio/turnwise-decision-lab/(?:blob|tree)/main/([^#?]*)(?:#([^?]*))?$")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
_FENCE = re.compile(r"^\s*(?:```|~~~)")
_CODE_SPAN = re.compile(r"`[^`]*`")
_INLINE = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^()\s>]+(?:\([^()\s]*\)[^()\s>]*)*)>?(?:\s+\"[^\"]*\")?\s*\)")
_REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)")
_HTML_LINK = re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_HTML_ANCHOR = re.compile(r"""<a\s+(?:name|id)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def github_slug(heading: str) -> str:
    """GitHub's heading anchor: rendered text, lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # [text](url) renders as text
    text = re.sub(r"<[^>]+>", "", text).replace("`", "").replace("*", "")
    text = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return text.replace(" ", "-")


def _unfenced_lines(text: str):
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            yield number, line


def markdown_anchors(path: Path) -> set[str]:
    found: set[str] = set()
    seen: dict[str, int] = {}
    for _, line in _unfenced_lines(path.read_text(encoding="utf-8")):
        found.update(a.lower() for a in _HTML_ANCHOR.findall(line))
        match = _HEADING.match(line)
        if match:
            base = github_slug(match.group(1))
            count = seen.get(base, 0)
            found.add(base if count == 0 else f"{base}-{count}")  # GitHub numbers repeated headings
            seen[base] = count + 1
    return found


def page_links(path: Path):
    """(line number, target) for every link the page makes."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        for number, line in enumerate(text.splitlines(), 1):
            for target in _HTML_LINK.findall(line):
                yield number, target
        return
    for number, line in _unfenced_lines(text):
        line = _CODE_SPAN.sub("", line)
        for target in _INLINE.findall(line):
            yield number, target
        definition = _REF_DEF.match(line)
        if definition:
            yield number, definition.group(1)
        for target in _HTML_LINK.findall(line):
            yield number, target


def link_problem(root: Path, page: Path, target: str) -> str | None:
    """Why ``target`` (linked from ``page``) does not resolve, or None. External URLs are not checked."""
    if target.startswith(("mailto:", "data:", "javascript:")) or "{" in target:
        return None  # not a navigable link, or a template placeholder inside generated HTML/JS
    repo_link = _REPO_URL.match(target)
    if repo_link:
        dest, anchor = root / unquote(repo_link.group(1)), repo_link.group(2) or ""
    elif _SCHEME.match(target) or target.startswith("//"):
        return None
    else:
        path_part, _, anchor = target.partition("#")
        dest = page if not path_part else page.parent / unquote(path_part)
    dest = dest.resolve()
    if dest != root and root not in dest.parents:
        return f"leaves the repository: {target}"
    if not dest.exists():
        return f"missing target: {target}"
    if anchor and dest.suffix == ".md" and unquote(anchor).lower() not in markdown_anchors(dest):
        return f"missing anchor: {target}"
    return None


def pages(root: Path):
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name.endswith((".md", ".html")):
                yield Path(base) / name


def scan(root: Path) -> tuple[list[str], int, int]:
    problems, links, anchored = [], 0, 0
    for page in pages(root):
        for number, target in page_links(page):
            links += 1
            anchored += "#" in target and not _SCHEME.match(target)
            problem = link_problem(root, page, target)
            if problem:
                problems.append(f"{page.relative_to(root).as_posix()}:{number}: {problem}")
    return problems, links, anchored


class RepositoryLinks(unittest.TestCase):
    def test_every_internal_link_and_anchor_resolves(self):
        problems, links, anchored = scan(ROOT)
        self.assertEqual(problems, [])
        # Guard against a regex change that silently checks nothing (315 links, 12 relative anchors on 2026-11-21).
        self.assertGreater(links, 200)
        self.assertGreater(anchored, 5)


class CheckerSelfTest(unittest.TestCase):
    """The checker must catch each kind of break and accept each kind of valid link."""

    def build(self, files: dict[str, str]) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for rel, text in files.items():
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp / rel).write_text(text, encoding="utf-8")
        return tmp.resolve()

    def test_each_kind_of_break_is_reported(self):
        root = self.build({
            "docs/a.md": "# Title\n\n## What CI verifies on `main`\n",
            "docs/index.md": (
                "[missing file](nope.md)\n"
                "[missing anchor](a.md#not-a-heading)\n"
                "[outside](../../etc/passwd)\n"
                "[repo blob](https://github.com/dgenio/turnwise-decision-lab/blob/main/docs/gone.md)\n"
                "[ref][r]\n\n[r]: ../NOPE.md\n"
                '<a href="missing.html">x</a>\n'),
        })
        problems, _, _ = scan(root)
        self.assertEqual(len(problems), 6, problems)
        for fragment in ("nope.md", "a.md#not-a-heading", "etc/passwd", "docs/gone.md", "NOPE.md", "missing.html"):
            self.assertTrue(any(fragment in p for p in problems), fragment)

    def test_valid_links_code_and_external_urls_pass(self):
        root = self.build({
            "AGENTS.md": "# Agents\n\n## Paid providers, secrets and data\n\n## Notes\n\n## Notes\n",
            "docs/a.md": "# Title\n\n## What CI verifies on `main`\n\n<a name=\"custom\"></a>\n",
            "docs/index.md": (
                "[heading with code](a.md#what-ci-verifies-on-main)\n"
                "[punctuation](../AGENTS.md#paid-providers-secrets-and-data)\n"
                "[repeated heading](../AGENTS.md#notes-1)\n"
                "[explicit anchor](a.md#custom)\n"
                "[same file](#links)\n"
                "[directory](../docs)\n"
                "[repo blob](https://github.com/dgenio/turnwise-decision-lab/blob/main/AGENTS.md)\n"
                "[external](https://example.com/not/checked) [issue](https://github.com/dgenio/turnwise-decision-lab/issues/23)\n"
                "`[code span](nope.md)`\n\n```\n[fenced](nope.md)\n```\n\n## Links\n"),
        })
        problems, links, _ = scan(root)
        self.assertEqual(problems, [])
        self.assertEqual(links, 9)  # code spans and fenced blocks are not links

    def test_slugs_follow_github(self):
        self.assertEqual(github_slug("What CI verifies on `main`"), "what-ci-verifies-on-main")
        self.assertEqual(github_slug("Paid providers, secrets and data"), "paid-providers-secrets-and-data")
        self.assertEqual(github_slug("Scientific null, ablations and kill criteria"),
                         "scientific-null-ablations-and-kill-criteria")
        self.assertEqual(github_slug("A [linked](x.md) **bold** title"), "a-linked-bold-title")


if __name__ == "__main__":
    unittest.main()
