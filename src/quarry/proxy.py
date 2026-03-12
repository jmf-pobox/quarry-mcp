# ruff: noqa: S310 — URLs constructed from known constants, not user input
"""Download and install the ``mcp-proxy`` binary from GitHub Releases.

The proxy bridges MCP stdio transport to the quarry daemon over WebSocket,
eliminating Python startup cost for every Claude Code session.
"""

from __future__ import annotations

import hashlib
import logging
import platform
import shutil
import stat
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO = "punt-labs/mcp-proxy"
_INSTALL_DIR = Path.home() / ".local" / "bin"
_BINARY_NAME = "mcp-proxy"


def _asset_name() -> str:
    """Return the platform-specific asset name for the current machine."""
    system = platform.system().lower()  # darwin, linux
    machine = platform.machine().lower()  # arm64, x86_64, aarch64

    if system not in ("darwin", "linux"):
        msg = f"Unsupported platform: {system}"
        raise SystemExit(msg)

    arch_map = {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86_64": "amd64",
        "amd64": "amd64",
    }
    arch = arch_map.get(machine)
    if arch is None:
        msg = f"Unsupported architecture: {machine}"
        raise SystemExit(msg)

    return f"mcp-proxy-{system}-{arch}"


def _latest_version() -> str:
    """Fetch the latest release tag from GitHub."""
    url = f"https://api.github.com/repos/{_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        import json  # noqa: PLC0415

        data = json.loads(resp.read())
    return str(data["tag_name"])


def _download_url(version: str, asset: str) -> str:
    """Construct the download URL for a release asset."""
    return f"https://github.com/{_REPO}/releases/download/{version}/{asset}"


def _checksums_url(version: str) -> str:
    """Construct the download URL for the checksums file."""
    return f"https://github.com/{_REPO}/releases/download/{version}/checksums.txt"


def _verify_checksum(binary_path: Path, version: str, asset: str) -> None:
    """Verify SHA256 checksum of downloaded binary against release checksums."""
    url = _checksums_url(version)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        checksums_text = resp.read().decode()

    expected = None
    for line in checksums_text.strip().splitlines():
        sha, name = line.split(None, 1)
        if name.strip() == asset:
            expected = sha
            break

    if expected is None:
        msg = f"No checksum found for {asset} in release {version}"
        raise ValueError(msg)

    actual = hashlib.sha256(binary_path.read_bytes()).hexdigest()
    if actual != expected:
        binary_path.unlink()
        msg = f"Checksum mismatch for {asset}: expected {expected}, got {actual}"
        raise ValueError(msg)


def installed_version() -> str | None:
    """Return the installed mcp-proxy path if on PATH, else None."""
    path = shutil.which(_BINARY_NAME)
    return path if path else None


def install(*, version: str | None = None) -> str:
    """Download and install mcp-proxy to ~/.local/bin/.

    Returns a status message.
    """
    if version is None:
        version = _latest_version()

    asset = _asset_name()
    url = _download_url(version, asset)

    _INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    dest = _INSTALL_DIR / _BINARY_NAME

    logger.info("Downloading %s %s", _BINARY_NAME, version)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())

    # Verify checksum before making executable
    _verify_checksum(dest, version, asset)

    # Make executable
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    logger.info("Installed %s to %s", _BINARY_NAME, dest)

    # Check if ~/.local/bin is on PATH
    import os  # noqa: PLC0415

    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if str(_INSTALL_DIR) not in path_dirs and str(_INSTALL_DIR) + "/" not in path_dirs:
        return (
            f"{_BINARY_NAME} {version} installed to {dest}\n"
            f"  Warning: {_INSTALL_DIR} is not on PATH"
        )

    return f"{_BINARY_NAME} {version} installed to {dest}"
