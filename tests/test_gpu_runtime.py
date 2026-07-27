"""Tests for quarry.gpu_runtime — NVIDIA GPU detection and onnxruntime swap.

The swap is subprocess orchestration, so it is exercised by asserting on the
argv issued to ``nvidia-smi``, ``ldconfig -p``, and ``uv pip`` — these are the
real system-boundary calls, not ML mocks. Each test declares the host's CUDA
runtime through the ``ldconfig`` branch of the shared ``_default_run`` mock.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from unittest.mock import MagicMock, patch

from quarry.gpu_runtime import GpuRuntime
from quarry.gpu_status import GpuStatus


def _which(present: Sequence[str]) -> Callable[[str], str | None]:
    """Build a ``shutil.which`` side effect where ``present`` names resolve."""

    def which_side_effect(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in present else None

    return which_side_effect


def _ldconfig_stdout(majors: Sequence[int]) -> str:
    """Render an ``ldconfig -p`` listing exposing ``libcudart.so.<major>``."""
    lines = [
        f"\tlibcudart.so.{m} (libc6,x86-64) => /lib/x86_64-linux-gnu/libcudart.so.{m}"
        for m in majors
    ]
    return "\n".join(["\t1234 libs found in cache '/etc/ld.so.cache'", *lines, ""])


def _is_provider_check(cmd: Sequence[str]) -> bool:
    """Return whether ``cmd`` is the in-subprocess onnxruntime provider probe."""
    return len(cmd) > 0 and cmd[0] == sys.executable and "-c" in cmd


def _is_ldconfig(cmd: Sequence[str]) -> bool:
    """Return whether ``cmd`` is the ``ldconfig -p`` loader-cache probe."""
    return len(cmd) >= 2 and cmd[0].endswith("ldconfig") and cmd[1] == "-p"


def _pip_install_specs(calls: Sequence[Sequence[str]]) -> list[str]:
    """Extract the package spec from every ``uv pip install <spec>`` call."""
    return [str(cmd[-1]) for cmd in calls if "pip" in cmd and "install" in cmd]


class _RunState:
    """Mutable flag tracking whether the GPU wheel install has run yet.

    The provider check runs twice with identical argv (once before the swap,
    once to verify the freshly-installed wheel). This lets the mock answer
    "CPU only" the first time and "CUDA available" after the install.
    """

    _installed: bool

    def __new__(cls) -> _RunState:
        self = super().__new__(cls)
        self._installed = False
        return self

    def mark_installed(self) -> None:
        """Record that a ``uv pip install`` of the GPU wheel has completed."""
        self._installed = True

    @property
    def installed(self) -> bool:
        """Return whether the GPU wheel install has run."""
        return self._installed


def _default_run(
    cmd: Sequence[str],
    *,
    ldconfig_majors: Sequence[int],
    cuda_after_install: bool,
    state: _RunState | None = None,
) -> MagicMock:
    """Default ``subprocess.run`` side effect for a healthy swap sequence.

    ``ldconfig_majors`` declares the host's loadable CUDA runtimes. The provider
    check reports CPU-only until the GPU wheel installs; after install it
    reports CUDA when ``cuda_after_install`` is set.
    """
    if _is_ldconfig(cmd):
        return MagicMock(returncode=0, stdout=_ldconfig_stdout(ldconfig_majors))
    if _is_provider_check(cmd):
        post_install = state.installed if state is not None else True
        cuda_up = cuda_after_install and post_install
        providers = (
            "CUDAExecutionProvider,CPUExecutionProvider"
            if cuda_up
            else "CPUExecutionProvider"
        )
        return MagicMock(returncode=0, stdout=f"{providers}\n")
    if state is not None and "pip" in cmd and "install" in cmd:
        state.mark_installed()
    return MagicMock(returncode=0)


class TestGpuRuntimeEnsure:
    """Tests for GpuRuntime.ensure() — GPU detection and onnxruntime swap."""

    def test_no_uv_on_path(self) -> None:
        """When uv is not on PATH, return early without any subprocess calls."""
        with patch("quarry.gpu_runtime.shutil.which", return_value=None):
            result = GpuRuntime.ensure()
        assert result == "uv not found, skipped GPU check"
        assert result is GpuStatus.NO_UV

    def test_no_nvidia_smi(self) -> None:
        """When nvidia-smi is absent, return 'no NVIDIA GPU'."""

        def which_side_effect(name: str) -> str | None:
            if name == "uv":
                return "/usr/bin/uv"
            if name == "nvidia-smi":
                return None
            return None

        with patch("quarry.gpu_runtime.shutil.which", side_effect=which_side_effect):
            result = GpuRuntime.ensure()
        assert result == "no NVIDIA GPU"

    def test_nvidia_smi_fails(self) -> None:
        """When nvidia-smi exists but fails, return 'no NVIDIA GPU'."""

        def which_side_effect(name: str) -> str | None:
            if name == "uv":
                return "/usr/bin/uv"
            if name == "nvidia-smi":
                return "/usr/bin/nvidia-smi"
            return None

        with (
            patch("quarry.gpu_runtime.shutil.which", side_effect=which_side_effect),
            patch(
                "quarry.gpu_runtime.subprocess.run",
                return_value=MagicMock(returncode=1),
            ),
        ):
            result = GpuRuntime.ensure()
        assert result == "no NVIDIA GPU"

    def test_cuda_already_available(self) -> None:
        """When CUDAExecutionProvider is already available, return early."""

        def which_side_effect(name: str) -> str | None:
            if name == "uv":
                return "/usr/bin/uv"
            if name == "nvidia-smi":
                return "/usr/bin/nvidia-smi"
            return None

        calls: list[list[str]] = []

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            if cmd[0] == "/usr/bin/nvidia-smi":
                return MagicMock(returncode=0)
            # Provider check subprocess — report CUDA available.
            if cmd[0] == sys.executable and "-c" in cmd:
                return MagicMock(
                    returncode=0,
                    stdout="CUDAExecutionProvider,CPUExecutionProvider\n",
                )
            return MagicMock(returncode=0)

        with (
            patch("quarry.gpu_runtime.shutil.which", side_effect=which_side_effect),
            patch("quarry.gpu_runtime.subprocess.run", side_effect=run_side_effect),
        ):
            result = GpuRuntime.ensure()

        assert result == "CUDA already available"
        # nvidia-smi + provider check = 2 subprocess calls, no pip commands.
        assert len(calls) == 2

    def test_cuda12_host_selects_cuda12_wheel(self) -> None:
        """A CUDA-12 host installs the CUDA-12-matched onnxruntime-gpu spec.

        Regression for quarry-ubj1: today's swap installs a bare
        ``onnxruntime-gpu>=1.18.0``, which the resolver pins to the newest
        published wheel (1.27.0, CUDA 13 / ``libcudart.so.13``) — unimportable
        on a CUDA-12 host. The fix must detect ``libcudart.so.12`` and install
        the CUDA-12 line ``onnxruntime-gpu>=1.19.0,<1.27.0``, never 1.27.0.
        """
        which = _which(["uv", "nvidia-smi", "ldconfig"])
        state = _RunState()
        calls: list[list[str]] = []

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            return _default_run(
                cmd, ldconfig_majors=(12,), cuda_after_install=True, state=state
            )

        with (
            patch("quarry.gpu_runtime.shutil.which", side_effect=which),
            patch("quarry.gpu_runtime.subprocess.run", side_effect=run_side_effect),
        ):
            result = GpuRuntime.ensure()

        assert result == GpuStatus.INSTALLED
        install_specs = _pip_install_specs(calls)
        # The CUDA-12-matched spec is installed …
        assert "onnxruntime-gpu>=1.19.0,<1.27.0" in install_specs
        # … and NOT the old unbounded spec (which resolves to the CUDA-13 1.27.0
        # wheel) nor the CUDA-13 spec whose floor is 1.27.0.
        assert "onnxruntime-gpu>=1.18.0" not in install_specs
        assert "onnxruntime-gpu>=1.27.0" not in install_specs

    def test_swap_success(self) -> None:
        """When nvidia-smi works and CUDA not available, swap succeeds."""
        which = _which(["uv", "nvidia-smi", "ldconfig"])
        state = _RunState()
        call_count = 0

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return _default_run(
                cmd, ldconfig_majors=(12,), cuda_after_install=True, state=state
            )

        with (
            patch("quarry.gpu_runtime.shutil.which", side_effect=which),
            patch(
                "quarry.gpu_runtime.subprocess.run",
                side_effect=run_side_effect,
            ),
        ):
            result = GpuRuntime.ensure()

        assert result == "onnxruntime-gpu installed"
        # nvidia-smi + provider check + ldconfig + uninstall + install +
        # post-install verify = 6 subprocess calls.
        assert call_count == 6

    def test_swap_failure_restores_cpu(self) -> None:
        """When the CUDA-matched onnxruntime-gpu install fails, CPU is restored."""
        which = _which(["uv", "nvidia-smi", "ldconfig"])
        calls: list[list[str]] = []

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            if _is_ldconfig(cmd):
                return MagicMock(returncode=0, stdout=_ldconfig_stdout((12,)))
            if _is_provider_check(cmd):
                return MagicMock(returncode=0, stdout="CPUExecutionProvider\n")
            # nvidia-smi OK, uninstall OK, gpu install fails, cpu restore OK.
            if "onnxruntime-gpu>=1.19.0,<1.27.0" in cmd:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        with (
            patch("quarry.gpu_runtime.shutil.which", side_effect=which),
            patch("quarry.gpu_runtime.subprocess.run", side_effect=run_side_effect),
        ):
            result = GpuRuntime.ensure()

        assert result == "onnxruntime-gpu install failed, CPU restored"
        # CPU restore was issued exactly once.
        restore_calls = [c for c in calls if "onnxruntime>=1.18.0" in c]
        assert len(restore_calls) == 1
        # Return value distinguishes from the "restore also failed" case.
        assert "also failed" not in result

    def test_swap_failure_restore_also_fails(self) -> None:
        """When both GPU install and CPU restore fail, return a distinct message."""
        which = _which(["uv", "nvidia-smi", "ldconfig"])

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            if _is_ldconfig(cmd):
                return MagicMock(returncode=0, stdout=_ldconfig_stdout((12,)))
            if _is_provider_check(cmd):
                return MagicMock(returncode=0, stdout="CPUExecutionProvider\n")
            # nvidia-smi OK, uninstall OK, gpu install fails, cpu restore fails.
            if "onnxruntime-gpu>=1.19.0,<1.27.0" in cmd:
                return MagicMock(returncode=1)
            if "onnxruntime>=1.18.0" in cmd:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        with (
            patch("quarry.gpu_runtime.shutil.which", side_effect=which),
            patch("quarry.gpu_runtime.subprocess.run", side_effect=run_side_effect),
        ):
            result = GpuRuntime.ensure()

        assert result == "onnxruntime-gpu install failed, CPU restore also failed"

    def test_swap_success_clears_module_cache(self) -> None:
        """After a successful swap, 'onnxruntime' must not remain in sys.modules."""
        import sys as _sys

        which = _which(["uv", "nvidia-smi", "ldconfig"])
        state = _RunState()
        mock_ort = MagicMock()

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            return _default_run(
                cmd, ldconfig_majors=(12,), cuda_after_install=True, state=state
            )

        with (
            patch("quarry.gpu_runtime.shutil.which", side_effect=which),
            patch(
                "quarry.gpu_runtime.subprocess.run",
                side_effect=run_side_effect,
            ),
            patch.dict("sys.modules", {"onnxruntime": mock_ort}),
        ):
            result = GpuRuntime.ensure()
            # Assert inside the patch.dict context — on exit it restores
            # the original sys.modules state, which would re-add the key.
            assert "onnxruntime" not in _sys.modules

        assert result == "onnxruntime-gpu installed"

    def test_cuda13_host_selects_cuda13_wheel(self) -> None:
        """A CUDA-13 host installs the CUDA-13 line ``onnxruntime-gpu>=1.27.0``."""
        which = _which(["uv", "nvidia-smi", "ldconfig"])
        state = _RunState()
        calls: list[list[str]] = []

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            return _default_run(
                cmd, ldconfig_majors=(13,), cuda_after_install=True, state=state
            )

        with (
            patch("quarry.gpu_runtime.shutil.which", side_effect=which),
            patch("quarry.gpu_runtime.subprocess.run", side_effect=run_side_effect),
        ):
            result = GpuRuntime.ensure()

        assert result == GpuStatus.INSTALLED
        install_specs = _pip_install_specs(calls)
        assert "onnxruntime-gpu>=1.27.0" in install_specs
        assert "onnxruntime-gpu>=1.19.0,<1.27.0" not in install_specs

    def test_both_cuda_majors_picks_highest(self) -> None:
        """With both libcudart.so.12 and .so.13 loadable, the newer line wins."""
        which = _which(["uv", "nvidia-smi", "ldconfig"])
        state = _RunState()
        calls: list[list[str]] = []

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            return _default_run(
                cmd, ldconfig_majors=(12, 13), cuda_after_install=True, state=state
            )

        with (
            patch("quarry.gpu_runtime.shutil.which", side_effect=which),
            patch("quarry.gpu_runtime.subprocess.run", side_effect=run_side_effect),
        ):
            result = GpuRuntime.ensure()

        assert result == GpuStatus.INSTALLED
        install_specs = _pip_install_specs(calls)
        # Highest mappable major (13) selected, not the 12 line.
        assert "onnxruntime-gpu>=1.27.0" in install_specs
        assert "onnxruntime-gpu>=1.19.0,<1.27.0" not in install_specs

    def test_gpu_present_no_libcudart_keeps_cpu(self) -> None:
        """GPU present but no libcudart on the loader path → CUDA_UNSUPPORTED.

        The ``ldconfig -p`` cache lists no ``libcudart.so.N``. No
        ``onnxruntime-gpu`` build can be proven to import, so none is installed
        and the working CPU runtime is kept (a recovered warning, not a failure).
        """
        which = _which(["uv", "nvidia-smi", "ldconfig"])
        calls: list[list[str]] = []

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            return _default_run(cmd, ldconfig_majors=(), cuda_after_install=False)

        with (
            patch("quarry.gpu_runtime.shutil.which", side_effect=which),
            patch("quarry.gpu_runtime.subprocess.run", side_effect=run_side_effect),
        ):
            result = GpuRuntime.ensure()

        assert result == GpuStatus.CUDA_UNSUPPORTED
        assert result.is_recovered is True
        assert result.is_failure is False
        # No onnxruntime-gpu install command was issued.
        assert not any("onnxruntime-gpu" in spec for spec in _pip_install_specs(calls))

    def test_unknown_cuda_major_does_not_mispin(self) -> None:
        """A CUDA major with no table entry (14) must not fall back to 12/13.

        ``ldconfig`` reports only ``libcudart.so.14``. The selector has no
        mapping for 14, so it must keep CPU and warn — never silently mis-pin to
        the 12 or 13 spec. This is the "don't guess" guarantee.
        """
        which = _which(["uv", "nvidia-smi", "ldconfig"])
        calls: list[list[str]] = []

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            return _default_run(cmd, ldconfig_majors=(14,), cuda_after_install=False)

        with (
            patch("quarry.gpu_runtime.shutil.which", side_effect=which),
            patch("quarry.gpu_runtime.subprocess.run", side_effect=run_side_effect),
        ):
            result = GpuRuntime.ensure()

        assert result == GpuStatus.CUDA_UNSUPPORTED
        # Crucially: no onnxruntime-gpu spec of any CUDA line was installed.
        assert not any("onnxruntime-gpu" in spec for spec in _pip_install_specs(calls))
        # The status renders "running on CPU" — the display consumed by doctor.
        assert "running on CPU" in result

    def test_ldconfig_absent_keeps_cpu(self) -> None:
        """GPU present but ``ldconfig`` not on PATH → CUDA_UNSUPPORTED, keep CPU.

        Guards the boundary where the probe tool itself is missing: detection
        yields the empty set and the swap fails loud rather than guessing.
        """
        # Note: ldconfig NOT in the resolvable set.
        which = _which(["uv", "nvidia-smi"])
        calls: list[list[str]] = []

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            if _is_provider_check(cmd):
                return MagicMock(returncode=0, stdout="CPUExecutionProvider\n")
            return MagicMock(returncode=0)

        with (
            patch("quarry.gpu_runtime.shutil.which", side_effect=which),
            patch("quarry.gpu_runtime.subprocess.run", side_effect=run_side_effect),
        ):
            result = GpuRuntime.ensure()

        assert result == GpuStatus.CUDA_UNSUPPORTED
        # ldconfig was never invoked (shutil.which returned None for it) …
        assert not any(_is_ldconfig(c) for c in calls)
        # … and no onnxruntime-gpu install was issued.
        assert not any("onnxruntime-gpu" in spec for spec in _pip_install_specs(calls))

    def test_install_succeeds_but_import_fails_restores_cpu(self) -> None:
        """A clean pip install that fails to import is caught → RESTORED.

        The CUDA-12 wheel installs (rc 0) but the post-install provider re-probe
        returns non-zero (simulating the ``libcudart`` ImportError). This must
        NOT be reported as INSTALLED: CPU is restored and the status is RESTORED,
        distinct from CUDA_UNSUPPORTED (a wheel WAS installed, then rolled back).
        """
        which = _which(["uv", "nvidia-smi", "ldconfig"])
        calls: list[list[str]] = []

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            if _is_ldconfig(cmd):
                return MagicMock(returncode=0, stdout=_ldconfig_stdout((12,)))
            if _is_provider_check(cmd):
                # Both the pre-swap and post-install probes fail to expose CUDA:
                # pre-swap CPU-only (swap needed), post-install import fails.
                return MagicMock(returncode=1, stdout="")
            return MagicMock(returncode=0)

        with (
            patch("quarry.gpu_runtime.shutil.which", side_effect=which),
            patch("quarry.gpu_runtime.subprocess.run", side_effect=run_side_effect),
        ):
            result = GpuRuntime.ensure()

        # RESTORED, never INSTALLED — a clean pip install that fails to import
        # must not be mistaken for success.
        assert result == GpuStatus.RESTORED
        install_specs = _pip_install_specs(calls)
        # The GPU wheel WAS installed (distinguishing from CUDA_UNSUPPORTED) …
        assert "onnxruntime-gpu>=1.19.0,<1.27.0" in install_specs
        # … then CPU was restored after the failed import re-probe.
        assert "onnxruntime>=1.18.0" in install_specs
