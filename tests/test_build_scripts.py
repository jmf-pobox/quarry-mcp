"""Tests for the release/build shell scripts under ``scripts/``.

These guard the Claude Desktop ``.mcpb`` build and the release-verify scripts.
The ``.mcpb`` distribution broke silently once (quarry-521g): ``build-mcpb.sh``
read a ``manifest.json`` that had been removed, no CI job built the bundle, and
no release ever attached the asset — so the README download link 404'd. Shell
scripts also had no shellcheck coverage beyond ``install.sh``, which is part of
how the broken ``build-mcpb.sh`` stayed broken.

The checks here are static plus shellcheck (no ``node``/``mcpb`` needed) so they
run in the same CI as the rest of the suite; the live bundle build is exercised
locally and in the release workflow, which installs ``mcpb``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
BUILD_MCPB = SCRIPTS_DIR / "build-mcpb.sh"
MANIFEST_TEMPLATE = SCRIPTS_DIR / "mcpb-manifest.template.json"
README_SHA_CHECK = SCRIPTS_DIR / "check-readme-install-sha.sh"
MCP_SERVER = REPO_ROOT / "src" / "quarry" / "mcp_server.py"

# The daemon-first install path: ``quarry install`` wires Claude Desktop to run
# the installed ``quarry`` binary as ``quarry mcp`` (a stdio client of quarryd,
# DES-031 v2.2). The bundle manifest must mirror exactly that.
EXPECTED_MCP_COMMAND = "quarry"
EXPECTED_MCP_ARGS = ["mcp"]


def _shell_scripts() -> list[Path]:
    return [*sorted(SCRIPTS_DIR.glob("*.sh")), REPO_ROOT / "install.sh"]


def _registered_tool_names() -> set[str]:
    """Wire names the MCP server registers, parsed from ``register()``.

    A tool registered with ``name="x"`` uses that wire name; otherwise the
    bound method name is the wire name (FastMCP's default).
    """
    source = MCP_SERVER.read_text()
    names: set[str] = set()
    pattern = re.compile(r'add_tool\(\s*self\.(\w+)\s*(?:,\s*name="(\w+)")?\s*\)')
    for method, override in pattern.findall(source):
        names.add(override or method)
    return names


@pytest.mark.parametrize("script", _shell_scripts(), ids=lambda p: p.name)
def test_shell_script_passes_shellcheck(script: Path) -> None:
    """Every shell script under ``scripts/`` (and install.sh) passes shellcheck.

    Per CLAUDE.md Class 5 / testing rule 6: shell scripts must pass
    ``shellcheck -x``. Extending this beyond install.sh closes the gap that let
    a broken build-mcpb.sh ship unlinted.
    """
    shellcheck_bin = shutil.which("shellcheck")
    if shellcheck_bin is None:
        pytest.fail(
            "shellcheck is required for shell-script linting but was not found "
            "on PATH. Install it in CI (apt-get install shellcheck) so this "
            "gate cannot be skipped."
        )
    result = subprocess.run(
        [shellcheck_bin, "-x", str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"shellcheck failed on {script.name}:\n{result.stdout}\n{result.stderr}"
    )


def test_build_mcpb_does_not_read_root_manifest() -> None:
    """build-mcpb.sh must not depend on a repo-root manifest.json.

    b2c9ffb removed the root manifest.json because the marketplace preferred it
    over .claude-plugin/plugin.json and stripped the plugin's slash commands.
    The manifest is generated into a staging dir instead; a reference to a root
    manifest would resurrect the broken build.
    """
    script = BUILD_MCPB.read_text()
    assert "open('manifest.json')" not in script
    assert "json.load(open('manifest.json'))" not in script
    assert "mcpb pack ." not in script, "must pack from staging, not the repo root"


def test_build_mcpb_stages_and_sources_version_from_pyproject() -> None:
    script = BUILD_MCPB.read_text()
    assert "dist/mcpb-staging" in script, "manifest must be staged, not at repo root"
    assert "pyproject.toml" in script, "version must come from pyproject.toml"
    assert "dist/punt-quarry.mcpb" in script, "stable-named copy must be produced"


def test_no_root_manifest_json_tracked() -> None:
    """A manifest.json at the repo root re-breaks plugin slash commands."""
    assert not (REPO_ROOT / "manifest.json").exists(), (
        "manifest.json must not exist at the repo root (b2c9ffb): the plugin "
        "marketplace would prefer it over .claude-plugin/plugin.json and drop "
        "the plugin's slash commands. Generate it into dist/mcpb-staging."
    )


def test_manifest_template_has_version_placeholder() -> None:
    template = json.loads(MANIFEST_TEMPLATE.read_text())
    assert template["version"] == "__VERSION__", (
        "template version must be a placeholder filled from pyproject at build "
        "time (PL-DI-5: pyproject is the single source of truth)"
    )


def test_manifest_template_mcp_config_matches_install_path() -> None:
    """The bundle's mcp_config must mirror how quarry install wires Desktop."""
    template = json.loads(MANIFEST_TEMPLATE.read_text())
    mcp_config = template["server"]["mcp_config"]
    assert mcp_config["command"] == EXPECTED_MCP_COMMAND
    assert mcp_config["args"] == EXPECTED_MCP_ARGS


def test_manifest_template_reflects_current_daemon_data_dir() -> None:
    template = json.loads(MANIFEST_TEMPLATE.read_text())
    assert "~/.punt-labs/quarry" in template["long_description"], (
        "manifest must reflect the current daemon data dir, not the stale "
        "~/.quarry/data"
    )
    assert "~/.quarry/data" not in json.dumps(template), "stale data dir present"


def test_manifest_template_tools_match_registered_mcp_tools() -> None:
    """The manifest tool list must equal the MCP server's registered wire names.

    A tool added to (or removed from) the server without updating the manifest
    is a surface-drift bug — the "every surface or none" invariant. Cross-check
    the two so drift fails a test.
    """
    template = json.loads(MANIFEST_TEMPLATE.read_text())
    manifest_tools = {tool["name"] for tool in template["tools"]}
    assert manifest_tools == _registered_tool_names()


def test_readme_install_sha_check_passes_on_current_readme() -> None:
    """The pinned README install SHA must match the current install.sh."""
    result = subprocess.run(
        ["bash", str(README_SHA_CHECK)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"README install-SHA check failed:\n{result.stdout}\n{result.stderr}"
    )


def test_readme_install_sha_check_rejects_stale_sha(tmp_path: Path) -> None:
    """A README pinning a SHA whose install.sh differs must fail the check.

    6f90f11 (v1.19.0) predates install.sh changes, so its installer differs from
    the current one — the exact stale-SHA class the check guards against.
    """
    stale = tmp_path / "README.md"
    stale.write_text(
        "curl -fsSL "
        "https://raw.githubusercontent.com/punt-labs/quarry/6f90f11/install.sh | sh\n"
    )
    result = subprocess.run(
        ["bash", str(README_SHA_CHECK)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env={"README_PATH": str(stale), "PATH": os.environ["PATH"]},
    )
    assert result.returncode != 0, "stale README install SHA must be rejected"
    assert "stale" in result.stderr.lower()
