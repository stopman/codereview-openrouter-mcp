"""Tests for PERSONAS.md loading: parsing, validation, and live reload."""

import os

import pytest

import codereview_openrouter_mcp.prompts as prompts
from codereview_openrouter_mcp.prompts import (
    EXPECTED_PERSONA_KEYS,
    PERSONAS_FILE,
    load_personas,
)


def test_personas_file_exists_at_repo_root():
    assert PERSONAS_FILE.name == "PERSONAS.md"
    assert PERSONAS_FILE.is_file(), f"PERSONAS.md missing at {PERSONAS_FILE}"


def test_personas_file_parses_with_exactly_the_expected_sections():
    personas = load_personas()
    assert set(personas) == set(EXPECTED_PERSONA_KEYS)
    for key, text in personas.items():
        assert text.strip(), f"Persona section '{key}' is empty"


def test_preamble_is_ignored():
    """Text above the first section marker must not leak into any prompt."""
    personas = load_personas()
    for key, text in personas.items():
        assert "Format rules" not in text, f"Preamble leaked into '{key}'"


def test_dispatch_serves_file_content():
    """The system prompts sent to models must come from PERSONAS.md."""
    personas = load_personas()
    assert prompts.get_review_system_prompt("sol") == personas["architect.review"]
    assert prompts.get_plan_review_system_prompt("opus") == personas["pragmatist.plan"]
    # Unmapped models fall back to the generalist prompts.
    assert prompts.get_review_system_prompt("nonexistent") == personas["generalist.review"]


def test_load_personas_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="PERSONAS.md"):
        load_personas(tmp_path / "PERSONAS.md")


def test_load_personas_missing_section(tmp_path):
    content = PERSONAS_FILE.read_text()
    content = content.replace("## PERSONA: detail.plan\n", "## DISABLED detail.plan\n")
    f = tmp_path / "PERSONAS.md"
    f.write_text(content)
    with pytest.raises(ValueError, match="Missing persona section.*detail.plan"):
        load_personas(f)


def test_load_personas_duplicate_section(tmp_path):
    content = PERSONAS_FILE.read_text() + "\n## PERSONA: architect.review\n\nagain\n"
    f = tmp_path / "PERSONAS.md"
    f.write_text(content)
    with pytest.raises(ValueError, match="Duplicate persona section.*architect.review"):
        load_personas(f)


def test_load_personas_unknown_section(tmp_path):
    content = PERSONAS_FILE.read_text() + "\n## PERSONA: hacker.review\n\nsome prompt\n"
    f = tmp_path / "PERSONAS.md"
    f.write_text(content)
    with pytest.raises(ValueError, match="Unknown persona section.*hacker.review"):
        load_personas(f)


def test_load_personas_empty_section(tmp_path):
    content = PERSONAS_FILE.read_text()
    # Move simplicity.review's marker to the end of file so its body is empty.
    content = content.replace("## PERSONA: simplicity.review\n", "")
    content += "\n## PERSONA: simplicity.review\n"
    f = tmp_path / "PERSONAS.md"
    f.write_text(content)
    with pytest.raises(ValueError, match="persona section"):
        load_personas(f)


def test_edits_apply_without_restart(tmp_path, monkeypatch):
    """Editing PERSONAS.md must change the prompts served on the next call."""
    f = tmp_path / "PERSONAS.md"
    original = PERSONAS_FILE.read_text()
    f.write_text(original)
    os.utime(f, (1_000_000_000, 1_000_000_000))

    monkeypatch.setattr(prompts, "PERSONAS_FILE", f)
    monkeypatch.setattr(prompts, "_cache", None)

    before = prompts.get_review_system_prompt("sol")
    assert "Custom Grumpy Architect" not in before

    f.write_text(original.replace(
        "Principal Software Architect", "Custom Grumpy Architect"
    ))
    os.utime(f, (1_000_000_001, 1_000_000_001))

    after = prompts.get_review_system_prompt("sol")
    assert "Custom Grumpy Architect" in after


def test_bad_edit_keeps_last_good_version(tmp_path, monkeypatch):
    """A malformed save while the server is running must not break reviews."""
    f = tmp_path / "PERSONAS.md"
    original = PERSONAS_FILE.read_text()
    f.write_text(original)
    os.utime(f, (1_000_000_000, 1_000_000_000))

    monkeypatch.setattr(prompts, "PERSONAS_FILE", f)
    monkeypatch.setattr(prompts, "_cache", None)

    good = prompts.get_review_system_prompt("sol")

    f.write_text("this file is now completely broken")
    os.utime(f, (1_000_000_001, 1_000_000_001))

    assert prompts.get_review_system_prompt("sol") == good
