"""RFC 6962 Merkle tree — root computation, inclusion proofs, consistency proofs.

A third sanctioned file in this domain beyond the four in AGENTS.md, for the same reason
as ``releases/differ.py``: pure computation with no database and no HTTP, which needs its
own unit tests and would otherwise bury ``service.py``.

**This module is a frozen contract.** Every sealed batch in every install depends on these
exact hash inputs. Changing a prefix, a concatenation order or the leaf encoding
invalidates every chain ever written. If a change looks necessary, it is a new algorithm
identifier alongside this one, never an edit to it.

Why RFC 6962 rather than the simpler "hash pairs, duplicate the last node when odd"
construction used by Bitcoin:

1. **Domain separation.** Leaves are prefixed 0x00 and interior nodes 0x01, so no leaf
   hash can ever be confused for an interior node. The duplicate-last-node approach
   admits two different leaf sets with the same root, which is exactly the property an
   audit log must not have.
2. **It is a published standard with independent implementations.** An auditor can verify
   a proof with Certificate Transparency tooling they already trust rather than with code
   we wrote. In an assurance product that is worth more than the elegance of the
   alternative.
3. **Consistency proofs come free**, which is what lets a customer holding last quarter's
   checkpoint confirm this quarter's log is an extension of it rather than a replacement.

Leaf input is the ASCII encoding of an event's ``content_digest`` — the string
``sha256:<64 hex chars>`` — and not the canonical event itself. That choice is
deliberate: an inclusion proof then reveals only sibling *digests*, so handing a customer
a proof about their own event discloses nothing about anybody else's.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"

# Root of the empty tree, per RFC 6962 section 2.1.
EMPTY_ROOT = hashlib.sha256(b"").digest()


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def leaf_hash(content_digest: str) -> bytes:
    """Hash one leaf. ``content_digest`` is the ``sha256:<hex>`` string from the event."""
    return _sha256(LEAF_PREFIX + content_digest.encode("ascii"))


def node_hash(left: bytes, right: bytes) -> bytes:
    return _sha256(NODE_PREFIX + left + right)


def _split_point(n: int) -> int:
    """Largest power of two strictly less than ``n``.

    RFC 6962 splits here rather than in the middle. The difference matters: this split
    makes every left subtree complete, which is what allows an append to reuse
    previously computed interior nodes and what makes consistency proofs short.
    """
    if n < 2:
        raise ValueError("split point is undefined for fewer than two leaves")
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def merkle_root(leaves: Sequence[bytes]) -> bytes:
    """Merkle Tree Hash over already-hashed leaves.

    Iterative rather than recursive: a batch can hold a large number of events and
    CPython's recursion limit is not a property worth depending on here.
    """
    if not leaves:
        return EMPTY_ROOT

    level = list(leaves)
    while len(level) > 1:
        nxt: list[bytes] = []
        # A complete pass over pairs, carrying any odd tail up unchanged. Carrying the
        # tail rather than duplicating it is what produces the RFC 6962 shape.
        for i in range(0, len(level) - 1, 2):
            nxt.append(node_hash(level[i], level[i + 1]))
        if len(level) % 2 == 1:
            nxt.append(level[-1])
        level = nxt

    return level[0]


def root_from_digests(content_digests: Sequence[str]) -> bytes:
    """Convenience for the sealer, which holds digest strings rather than hashes."""
    return merkle_root([leaf_hash(d) for d in content_digests])


def inclusion_proof(leaves: Sequence[bytes], index: int) -> list[bytes]:
    """Audit path proving ``leaves[index]`` is in the tree rooted at ``merkle_root``.

    Returns sibling hashes **ordered from the leaf upward**, which is the order RFC 6962
    defines for an audit path and therefore the order ``verify_inclusion`` and any
    third-party Certificate Transparency verifier expect. The recursive descent below
    naturally produces them top-down, so the result is reversed before returning.
    """
    n = len(leaves)
    if not 0 <= index < n:
        raise IndexError(f"leaf index {index} outside tree of size {n}")

    path: list[bytes] = []
    lo, hi = 0, n
    idx = index

    while hi - lo > 1:
        k = _split_point(hi - lo)
        if idx < k:
            # Target is in the left subtree, so the sibling is the whole right subtree.
            path.append(merkle_root(leaves[lo + k : hi]))
            hi = lo + k
        else:
            path.append(merkle_root(leaves[lo : lo + k]))
            lo = lo + k
            idx -= k

    path.reverse()
    return path


def verify_inclusion(
    leaf: bytes,
    index: int,
    tree_size: int,
    path: Sequence[bytes],
    expected_root: bytes,
) -> bool:
    """Recompute the root from a leaf and its audit path.

    This is the function an external auditor reimplements, so it takes only values that
    appear in a published proof and touches nothing else. It is a direct transcription
    of the verification algorithm in RFC 6962 section 2.1.1, walking from the leaf
    upward and tracking the leaf's position with ``fn`` and the last index of the
    current level with ``sn``.

    Two rejections are load-bearing rather than defensive. Stopping when ``sn`` reaches
    zero with path entries left over refuses an over-long proof, and requiring ``sn`` to
    be zero at the end refuses a truncated one. Without both, an attacker could pad or
    trim a path until it happened to verify.
    """
    if not 0 <= index < tree_size:
        return False

    fn = index
    sn = tree_size - 1
    computed = leaf

    for sibling in path:
        if sn == 0:
            return False

        if fn & 1 or fn == sn:
            computed = node_hash(sibling, computed)
            # Climbing past a right edge: skip the levels where this node is the
            # carried odd tail and therefore has no sibling to combine with.
            if not fn & 1:
                while fn and not fn & 1:
                    fn >>= 1
                    sn >>= 1
        else:
            computed = node_hash(computed, sibling)

        fn >>= 1
        sn >>= 1

    return sn == 0 and computed == expected_root


def format_hash(digest: bytes) -> str:
    """Wire and column form. The ``sha256:`` prefix is not decoration — it is what lets
    a second algorithm be introduced later without ambiguity about which one produced
    an existing row."""
    return f"sha256:{digest.hex()}"


def parse_hash(value: str) -> bytes:
    expected_prefix = "sha256:"
    if not value.startswith(expected_prefix):
        raise ValueError(f"unsupported digest algorithm in {value!r}")
    raw = bytes.fromhex(value[len(expected_prefix) :])
    if len(raw) != 32:
        raise ValueError(f"expected 32 bytes of sha256, got {len(raw)}")
    return raw
