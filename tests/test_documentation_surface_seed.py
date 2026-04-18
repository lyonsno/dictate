from pathlib import Path
import subprocess
import sys

from spoke.documentation_surfaces import render_manifest, seed_entries_from_markdown


def test_seed_entries_infers_routes_from_markdown_sections():
    markdown = """
# Developer And Operator Surfaces

## Bounded Post-Transcription Repair Pass

`spoke` keeps a bounded post-transcription repair pass for recurring
project-specific vocabulary observed in real logs.

## Smoke-Surface Runtime Affordances

On local smoke surfaces, the menubar also exposes launch-target switching,
source/branch visibility, and the status HUD (`Terror Form`) so you can confirm
which runtime surface is actually live.
"""

    entries = seed_entries_from_markdown(
        source_path=Path("docs/developer-operator-surfaces.md"),
        markdown=markdown,
    )

    repair = entries["bounded_post_transcription_repair_pass"]
    assert repair["audience"] == "developer"
    assert repair["canonical_surface"] == "docs/developer-operator-surfaces.md"
    assert repair["public_readme"] == "omit"
    assert repair["canonical_markers"] == ["Bounded Post-Transcription Repair Pass"]
    assert repair["public_readme_absent_markers"] == [
        "Bounded Post-Transcription Repair Pass"
    ]

    smoke = entries["smoke_surface_runtime_affordances"]
    assert smoke["audience"] == "operator"
    assert smoke["canonical_surface"] == "docs/developer-operator-surfaces.md"
    assert smoke["public_readme"] == "omit"
    assert smoke["canonical_markers"] == ["Smoke-Surface Runtime Affordances"]


def test_seed_entries_skips_existing_ids():
    markdown = """
## Smoke-Surface Runtime Affordances

Operator details.
"""

    entries = seed_entries_from_markdown(
        source_path=Path("docs/developer-operator-surfaces.md"),
        markdown=markdown,
        existing_ids={"smoke_surface_runtime_affordances"},
    )

    assert entries == {}


def test_seed_script_dry_run_is_silent_when_manifest_is_already_seated(tmp_path):
    doc = tmp_path / "developer-operator-surfaces.md"
    doc.write_text(
        """
## Bounded Post-Transcription Repair Pass

Developer details.
""".strip()
    )
    manifest = tmp_path / "documentation_surfaces.toml"
    manifest.write_text(
        render_manifest(
            {
                "capabilities": {
                    "bounded_post_transcription_repair_pass": {
                        "audience": "developer",
                        "canonical_surface": doc.as_posix(),
                        "public_readme": "omit",
                        "reason": "Settled route.",
                        "revisit_when": "Never for this test.",
                        "canonical_markers": ["Bounded Post-Transcription Repair Pass"],
                        "public_readme_absent_markers": ["Bounded Post-Transcription Repair Pass"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "seed-documentation-surfaces.py"
    result = subprocess.run(
        [sys.executable, str(script), str(doc), "--output", str(manifest), "--dry-run"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout == ""
    assert result.stderr == ""


def test_seed_script_dry_run_prints_only_missing_entries(tmp_path):
    doc = tmp_path / "developer-operator-surfaces.md"
    doc.write_text(
        """
## Bounded Post-Transcription Repair Pass

Developer details.

## Smoke-Surface Runtime Affordances

Operator details.
""".strip()
    )
    manifest = tmp_path / "documentation_surfaces.toml"
    manifest.write_text(
        render_manifest(
            {
                "capabilities": {
                    "bounded_post_transcription_repair_pass": {
                        "audience": "developer",
                        "canonical_surface": doc.as_posix(),
                        "public_readme": "omit",
                        "reason": "Settled route.",
                        "revisit_when": "Never for this test.",
                        "canonical_markers": ["Bounded Post-Transcription Repair Pass"],
                        "public_readme_absent_markers": ["Bounded Post-Transcription Repair Pass"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "seed-documentation-surfaces.py"
    result = subprocess.run(
        [sys.executable, str(script), str(doc), "--output", str(manifest), "--dry-run"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "[capabilities.smoke_surface_runtime_affordances]" in result.stdout
    assert "[capabilities.bounded_post_transcription_repair_pass]" not in result.stdout
