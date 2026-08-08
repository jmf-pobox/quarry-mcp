"""The daemon's bind options: one value object that normalizes itself.

Separated from the launcher because the normalization is the value's own
invariant — it reads and rewrites only these six fields and returns another
``BindOptions`` — while the launcher's job is turning a normalized bind into a
running server. Keeping them together left the launcher holding a forty-line
policy about a type it merely receives.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Self, final

from quarry.net import LoopbackPolicy


@final
@dataclass(frozen=True, slots=True)
class BindOptions:
    """The daemon's parsed bind options as one value, not a parameter list."""

    host: str
    port: int
    db: str
    api_key: str | None
    cors_origins: tuple[str, ...]
    tls: bool

    def normalized(self) -> Self:
        """Return these options normalized, ready for the bind.

        Normalization lives ON the value rather than on the launcher: it reads
        and rewrites only these fields, so it is the object's own invariant.
        Applied once at the single launcher boundary — the actual bind point —
        so the bind, the key gate, and the client all agree.  The three steps
        are separate methods because each answers a different question, and
        each carries the failure it exists to prevent.
        """
        api_key = self._stripped_key()
        self._refuse_split_key(api_key)
        return replace(self, api_key=api_key, host=self._canonical_host())

    def _stripped_key(self) -> str | None:
        """Return the api_key with blank forms collapsed to ``None``.

        ``enforce_bind_key``, ``_effective_key`` and ``DaemonServer`` must all
        see the same value.  Without this a whitespace-only ``QUARRY_API_KEY``
        is truthy at the gate: a loopback bind would fail to mint and then exit
        at the daemon boundary (won't start), and a network bind would pass the
        gate only to fail inconsistently later.  Collapsed here, a whitespace
        key is absent everywhere — loopback mints, network is refused AT the
        gate.
        """
        return (self.api_key or "").strip() or None

    @staticmethod
    def _refuse_split_key(api_key: str | None) -> None:
        """Exit on an api_key with INTERNAL whitespace, before anything binds.

        The bearer scheme parses ``Authorization`` with ``.split()`` and
        requires EXACTLY two parts (``daemon/routes/base.py``), so
        ``Bearer abc def`` yields three and NO client can ever authenticate —
        quarryd would boot and then 401 every request, a silently unreachable
        daemon from one bad environment variable.  Surrounding whitespace is
        already gone by here, so any space that remains is internal.
        """
        if api_key is not None and any(c.isspace() for c in api_key):
            msg = (
                "QUARRY_API_KEY must not contain whitespace — the HTTP bearer "
                "scheme splits the Authorization header on whitespace, so an "
                "embedded space would make the daemon permanently "
                "unauthenticatable."
            )
            raise SystemExit(msg)

    def _canonical_host(self) -> str:
        """Return the host with a loopback NAME resolved to its IPv4 literal.

        A managed service-unit start and a direct ``quarryd --host localhost``
        both pass through here, so the bind agrees with the install probe and
        ``quarry login``, which use 127.0.0.1.  Binding the name would land on
        ``::1`` on an IPv6-preferring host while the client checks 127.0.0.1 (a
        false timeout, then a 401).  An explicit ``::1`` or a non-loopback
        ``0.0.0.0`` is left as the operator set it; the key gate then runs on
        the canonical host, so ``localhost`` reads as loopback and needs no
        operator key.
        """
        return LoopbackPolicy(self.host).canonical_host
