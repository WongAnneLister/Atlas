"""Check interview notes against docs/notes/TEMPLATE.md rules, or build INTERVIEW_NOTES.md.

Usage:
    python scripts/check_notes.py          # check, exit 1 on any problem
    python scripts/check_notes.py --build  # concatenate notes into docs/INTERVIEW_NOTES.md
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTES_DIR = Path("docs/notes")
PROGRESS_FILE = Path("docs/PROGRESS.md")
OUTPUT_FILE = Path("docs/INTERVIEW_NOTES.md")

SECTIONS = ["What", "Why", "Number", "Trade-off", "Likely follow-up question"]
MIN_SENTENCES = 2
MAX_SENTENCES = 4
MAX_WORDS = 15
BANNED_WORDS = [
    "leverage",
    "utilize",
    "robust",
    "seamless",
    "cutting-edge",
    "state-of-the-art",
    "synergy",
    "holistic",
]
NO_NUMBER_PHRASE = "No number yet"

NOTE_NAME = re.compile(r"^\d{2}-[a-z0-9-]+\.md$")
HEADING = re.compile(r"^\*\*(.+?)\*\*\s*$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
NUMBER = re.compile(r"\d+(?:\.\d+)?%?")
# Commit references like "commit 08" or "commits 09-12" are not metrics.
COMMIT_REF = re.compile(r"\bcommits?\s+\d+(?:\s*[-\N{EN DASH}]\s*\d+)?", re.IGNORECASE)
PROGRESS_ROW = re.compile(r"^\|\s*(\d{2})\s*\|[^|]*\|\s*([^|]+?)\s*\|")


@dataclass(frozen=True)
class Problem:
    path: Path
    message: str

    def __str__(self) -> str:
        return f"{self.path.as_posix()}: {self.message}"


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences on ., ! or ? followed by whitespace."""
    flat = " ".join(text.split())
    return [s for s in SENTENCE_END.split(flat) if s]


def parse_sections(text: str) -> tuple[list[str], dict[str, str]]:
    """Return heading order and the body text under each bold heading."""
    order: list[str] = []
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = HEADING.match(line.strip())
        if match:
            current = match.group(1).strip()
            order.append(current)
            bodies[current] = []
        elif current is not None:
            bodies[current].append(line)
    return order, {k: "\n".join(v).strip() for k, v in bodies.items()}


def _check_prose(path: Path, name: str, text: str) -> list[Problem]:
    problems: list[Problem] = []
    sentences = split_sentences(text)
    if not MIN_SENTENCES <= len(sentences) <= MAX_SENTENCES:
        problems.append(Problem(path, f"'{name}' has {len(sentences)} sentences, need 2-4"))
    problems.extend(_check_lengths(path, name, sentences))
    return problems


def _check_lengths(path: Path, name: str, sentences: list[str]) -> list[Problem]:
    return [
        Problem(path, f"'{name}' sentence over {MAX_WORDS} words: \"{s}\"")
        for s in sentences
        if len(s.split()) > MAX_WORDS
    ]


def _check_number(path: Path, body: str, root: Path) -> list[Problem]:
    lines = body.splitlines()
    source_lines = [ln for ln in lines if ln.strip().startswith("Source:")]
    prose = "\n".join(ln for ln in lines if not ln.strip().startswith("Source:"))
    problems = _check_prose(path, "Number", prose)
    if NO_NUMBER_PHRASE in prose:
        leftover = NUMBER.findall(COMMIT_REF.sub("", prose))
        if leftover:
            problems.append(
                Problem(path, f"'Number' says '{NO_NUMBER_PHRASE}' but has numbers {leftover}")
            )
        return problems
    if not source_lines:
        problems.append(
            Problem(path, f"'Number' needs a 'Source:' line or the phrase '{NO_NUMBER_PHRASE}'")
        )
        return problems
    source = root / source_lines[0].split(":", 1)[1].strip()
    if not source.is_file():
        problems.append(Problem(path, f"source file not found: {source_lines[0].strip()}"))
        return problems
    source_text = source.read_text(encoding="utf-8")
    for number in NUMBER.findall(COMMIT_REF.sub("", prose)):
        if number not in source_text:
            problems.append(Problem(path, f"number '{number}' not found in {source.name}"))
    return problems


def _check_follow_up(path: Path, body: str) -> list[Problem]:
    q_lines = [ln.strip()[2:].strip() for ln in body.splitlines() if ln.strip().startswith("Q:")]
    a_parts = body.split("A:", 1)
    if not q_lines or len(a_parts) < 2:
        return [Problem(path, "'Likely follow-up question' needs a 'Q:' line and an 'A:' answer")]
    problems = _check_lengths(path, "Q", split_sentences(q_lines[0]))
    problems.extend(_check_prose(path, "A", a_parts[1]))
    return problems


def check_note(path: Path, root: Path) -> list[Problem]:
    """Return every rule violation in one note (empty list means it passes)."""
    text = path.read_text(encoding="utf-8")
    order, bodies = parse_sections(text)
    if order != SECTIONS:
        return [Problem(path, f"headings must be {SECTIONS} in order, found {order}")]
    problems: list[Problem] = []
    for word in BANNED_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
            problems.append(Problem(path, f"banned word: '{word}'"))
    for name in ("What", "Why", "Trade-off"):
        problems.extend(_check_prose(path, name, bodies[name]))
    problems.extend(_check_number(path, bodies["Number"], root))
    problems.extend(_check_follow_up(path, bodies["Likely follow-up question"]))
    return problems


def note_files(root: Path) -> list[Path]:
    notes_dir = root / NOTES_DIR
    if not notes_dir.is_dir():
        return []
    return sorted(p for p in notes_dir.iterdir() if NOTE_NAME.match(p.name))


def check_progress(root: Path) -> list[Problem]:
    """Every commit row marked `done` in PROGRESS.md must have its note file."""
    progress = root / PROGRESS_FILE
    if not progress.is_file():
        return []
    have = {p.name[:2] for p in note_files(root)}
    problems: list[Problem] = []
    for line in progress.read_text(encoding="utf-8").splitlines():
        match = PROGRESS_ROW.match(line)
        if match and match.group(2).lower() == "done" and match.group(1) not in have:
            problems.append(Problem(progress, f"commit {match.group(1)} is done but has no note"))
    return problems


def check_all(root: Path) -> list[Problem]:
    problems: list[Problem] = []
    for path in note_files(root):
        problems.extend(check_note(path, root))
    problems.extend(check_progress(root))
    return problems


def build(root: Path) -> Path:
    """Concatenate all notes in commit order into one review file."""
    parts = ["# Interview notes\n\nGenerated by `make notes`. Do not edit by hand.\n"]
    parts.extend(p.read_text(encoding="utf-8").strip() + "\n" for p in note_files(root))
    out = root / OUTPUT_FILE
    out.write_text("\n---\n\n".join(parts), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="write docs/INTERVIEW_NOTES.md")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    if args.build:
        print(f"wrote {build(args.root)}")
        return 0
    problems = check_all(args.root)
    for problem in problems:
        print(problem)
    count = len(note_files(args.root))
    print(f"notes-check: {count} note(s), {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
