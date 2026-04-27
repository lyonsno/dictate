import ast
import tomllib
from pathlib import Path

import pytest


README = Path(__file__).resolve().parents[1] / "README.md"
REPO_ROOT = README.parent
DOCS = README.parent / "docs"
MANIFEST = DOCS / "documentation_surfaces.toml"


def read_readme() -> str:
    return README.read_text(encoding="utf-8")


def load_manifest() -> dict:
    with MANIFEST.open("rb") as fh:
        return tomllib.load(fh)


CAPABILITY_CASES = tuple(load_manifest()["capabilities"].items())


def test_manifest_capability_contract_tests_are_manifest_driven():
    manifest_capability_ids = set(load_manifest()["capabilities"])
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    hard_coded_ids: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in manifest_capability_ids:
                hard_coded_ids.add(node.value)

    assert hard_coded_ids == set()


def canonical_surface_path(canonical_surface: str) -> Path:
    surface_path = (REPO_ROOT / canonical_surface).resolve()
    repo_root = REPO_ROOT.resolve()
    if not surface_path.is_relative_to(repo_root):
        raise ValueError(f"canonical surface escapes repo root: {canonical_surface}")
    return surface_path


def test_canonical_surface_paths_are_repo_relative():
    assert canonical_surface_path("README.md") == README
    assert canonical_surface_path("docs/local-smoke-runbook.md") == DOCS / "local-smoke-runbook.md"


@pytest.mark.parametrize(
    ("capability_id", "capability"),
    CAPABILITY_CASES,
    ids=[capability_id for capability_id, _ in CAPABILITY_CASES],
)
def test_topothesia_manifest_routes_capabilities_to_declared_surfaces(capability_id, capability):
    assert capability_id
    assert capability["audience"] in {"developer", "operator", "public"}
    assert capability["public_readme"] in {"omit", "include"}
    assert capability["reason"]
    assert capability["revisit_when"]
    assert capability["canonical_markers"]
    assert canonical_surface_path(capability["canonical_surface"]).is_file()


@pytest.mark.parametrize(
    ("capability_id", "capability"),
    CAPABILITY_CASES,
    ids=[capability_id for capability_id, _ in CAPABILITY_CASES],
)
def test_capabilities_live_on_their_routed_documentation_surfaces(capability_id, capability):
    assert capability_id
    text = read_readme()
    surface_text = canonical_surface_path(capability["canonical_surface"]).read_text(
        encoding="utf-8"
    )

    for marker in capability["canonical_markers"]:
        assert marker in surface_text

    if capability["public_readme"] == "omit":
        for marker in capability.get("public_readme_absent_markers", []):
            assert marker not in text


def test_readme_mentions_current_public_assistant_capabilities():
    text = read_readme().lower()

    assert "brave search" in text
    assert "multimodal" in text
    assert "subagent" in text
    assert "narrator" in text
    assert "compact" in text


def test_readme_mentions_brave_search_api_key_setup():
    text = read_readme()

    assert "BRAVE_SEARCH_API_KEY" in text or "SPOKE_BRAVE_SEARCH_API_KEY" in text
