"""RFC 6962 Merkle tree tests.

These are the highest-consequence tests in the repository. ``merkle.py`` is a frozen
contract: every sealed batch in every install depends on its exact hash inputs, so a
change that alters a single byte of the construction silently invalidates every chain
ever written. These tests exist to make that change impossible to land accidentally.

The central test is ``test_matches_rfc6962_reference`` — the iterative implementation in
``merkle.py`` is cross-checked against an independent recursive transcription of the RFC
itself. Writing the reference separately is the point: two implementations of the same
spec agreeing is evidence, whereas one implementation agreeing with itself is not.
"""

from __future__ import annotations

import hashlib

import pytest

from app.domains.evidence import merkle


def digest_str(i: int) -> str:
    """A plausible ``content_digest`` for leaf ``i``, in the form the sealer holds."""
    return merkle.format_hash(hashlib.sha256(f"event-{i}".encode()).digest())


# ----------------------------------------------------------------------
# An independent transcription of RFC 6962 section 2.1, used as the oracle.
# Recursive and deliberately naive: it is meant to be obviously correct by
# inspection against the RFC text, not fast.
# ----------------------------------------------------------------------


def rfc6962_mth(leaves: list[bytes]) -> bytes:
    """MTH(D[n]) exactly as the RFC defines it.

    MTH({})      = SHA-256()
    MTH(D[1])    = the single leaf hash
    MTH(D[n])    = SHA-256(0x01 || MTH(D[0:k]) || MTH(D[k:n])),
                   k = largest power of two strictly less than n
    """
    if not leaves:
        return hashlib.sha256(b"").digest()
    if len(leaves) == 1:
        return leaves[0]

    k = 1
    while k * 2 < len(leaves):
        k *= 2
    return hashlib.sha256(b"\x01" + rfc6962_mth(leaves[:k]) + rfc6962_mth(leaves[k:])).digest()


# ----------------------------------------------------------------------
# Conformance
# ----------------------------------------------------------------------


def test_empty_root_is_sha256_of_empty_string() -> None:
    """RFC 6962 section 2.1 fixes the empty tree's hash. Pinned as a literal so a
    refactor cannot quietly redefine what "no evidence yet" hashes to."""
    assert hashlib.sha256(b"").digest() == merkle.EMPTY_ROOT
    assert merkle.merkle_root([]) == merkle.EMPTY_ROOT


def test_leaf_hash_is_prefixed_and_pinned() -> None:
    """The 0x00 prefix is the frozen part. Recomputed here from primitives rather than
    by calling the module, so this test fails if the prefix changes."""
    d = digest_str(0)
    assert merkle.leaf_hash(d) == hashlib.sha256(b"\x00" + d.encode("ascii")).digest()


def test_node_hash_is_prefixed_and_pinned() -> None:
    left, right = merkle.leaf_hash(digest_str(0)), merkle.leaf_hash(digest_str(1))
    assert merkle.node_hash(left, right) == hashlib.sha256(b"\x01" + left + right).digest()


def test_single_leaf_root_is_the_leaf_itself() -> None:
    leaf = merkle.leaf_hash(digest_str(0))
    assert merkle.merkle_root([leaf]) == leaf


@pytest.mark.parametrize("size", range(1, 34))
def test_matches_rfc6962_reference(size: int) -> None:
    """The iterative implementation must equal the recursive RFC definition.

    Swept across sizes 1..33 because the constructions only coincide if the odd tail is
    carried rather than duplicated, and the divergence appears at specific sizes —
    notably 3, 5, 7, 11 and 13, where the largest-power-of-two split is not the middle.
    """
    leaves = [merkle.leaf_hash(digest_str(i)) for i in range(size)]
    assert merkle.merkle_root(leaves) == rfc6962_mth(leaves)


def test_root_from_digests_matches_hashing_then_rooting() -> None:
    digests = [digest_str(i) for i in range(9)]
    assert merkle.root_from_digests(digests) == merkle.merkle_root(
        [merkle.leaf_hash(d) for d in digests]
    )


# ----------------------------------------------------------------------
# The security properties the construction was chosen for
# ----------------------------------------------------------------------


def test_leaf_and_node_hashes_cannot_collide() -> None:
    """Domain separation. Without distinct prefixes a leaf whose content happened to be
    two concatenated hashes would be indistinguishable from an interior node."""
    a, b = merkle.leaf_hash(digest_str(0)), merkle.leaf_hash(digest_str(1))
    parent = merkle.node_hash(a, b)

    # Feeding the raw concatenation through the leaf function must not reproduce the
    # interior node, which is precisely the second-preimage attack being prevented.
    assert merkle.leaf_hash((a + b).hex()) != parent


def test_odd_tail_is_carried_not_duplicated() -> None:
    """The Bitcoin-style construction duplicates the last node when a level is odd,
    which makes two different leaf sets share a root. That is the one property an audit
    log must not have, so it is tested directly rather than assumed."""
    leaves = [merkle.leaf_hash(digest_str(i)) for i in range(3)]

    # Three leaves, versus the same three with the last one repeated.
    assert merkle.merkle_root(leaves) != merkle.merkle_root([*leaves, leaves[-1]])


def test_order_is_part_of_the_root() -> None:
    leaves = [merkle.leaf_hash(digest_str(i)) for i in range(5)]
    reordered = [leaves[1], leaves[0], *leaves[2:]]
    assert merkle.merkle_root(leaves) != merkle.merkle_root(reordered)


def test_changing_one_leaf_changes_the_root() -> None:
    """Tamper detection, which is the entire claim made to an auditor."""
    original = [merkle.leaf_hash(digest_str(i)) for i in range(8)]
    tampered = list(original)
    tampered[3] = merkle.leaf_hash(digest_str(999))
    assert merkle.merkle_root(original) != merkle.merkle_root(tampered)


# ----------------------------------------------------------------------
# Inclusion proofs — what a customer is actually handed
# ----------------------------------------------------------------------


@pytest.mark.parametrize("size", [1, 2, 3, 4, 5, 7, 8, 9, 16, 17, 31])
def test_every_leaf_proves_inclusion(size: int) -> None:
    """Exhaustive over indices, not a sample. An off-by-one in the split logic tends to
    affect only the boundary indices, which is exactly where a sampled test looks away."""
    leaves = [merkle.leaf_hash(digest_str(i)) for i in range(size)]
    root = merkle.merkle_root(leaves)

    for index in range(size):
        path = merkle.inclusion_proof(leaves, index)
        assert merkle.verify_inclusion(leaves[index], index, size, path, root), (
            f"leaf {index} of {size} failed to verify"
        )


def test_proof_fails_against_a_different_root() -> None:
    leaves = [merkle.leaf_hash(digest_str(i)) for i in range(8)]
    path = merkle.inclusion_proof(leaves, 3)
    wrong_root = merkle.merkle_root(leaves[:7])

    assert not merkle.verify_inclusion(leaves[3], 3, 8, path, wrong_root)


def test_proof_fails_for_a_leaf_not_in_the_tree() -> None:
    leaves = [merkle.leaf_hash(digest_str(i)) for i in range(8)]
    root = merkle.merkle_root(leaves)
    path = merkle.inclusion_proof(leaves, 3)

    forged = merkle.leaf_hash(digest_str(999))
    assert not merkle.verify_inclusion(forged, 3, 8, path, root)


def test_proof_fails_when_replayed_at_the_wrong_index() -> None:
    leaves = [merkle.leaf_hash(digest_str(i)) for i in range(8)]
    root = merkle.merkle_root(leaves)
    path = merkle.inclusion_proof(leaves, 3)

    assert not merkle.verify_inclusion(leaves[3], 4, 8, path, root)


def test_padded_proof_is_rejected() -> None:
    """A verifier that ignores leftover path entries lets an attacker append siblings
    until a proof happens to verify. The length check is load-bearing."""
    leaves = [merkle.leaf_hash(digest_str(i)) for i in range(8)]
    root = merkle.merkle_root(leaves)
    path = merkle.inclusion_proof(leaves, 3)

    assert not merkle.verify_inclusion(leaves[3], 3, 8, [*path, leaves[0]], root)


def test_truncated_proof_is_rejected() -> None:
    leaves = [merkle.leaf_hash(digest_str(i)) for i in range(8)]
    root = merkle.merkle_root(leaves)
    path = merkle.inclusion_proof(leaves, 3)

    assert not merkle.verify_inclusion(leaves[3], 3, 8, path[:-1], root)


def test_index_outside_the_tree_is_rejected_not_crashed() -> None:
    """``verify_inclusion`` is reachable from the trust portal with caller-supplied
    numbers, so a bad index must be a false rather than a 500."""
    leaves = [merkle.leaf_hash(digest_str(i)) for i in range(4)]
    root = merkle.merkle_root(leaves)

    assert not merkle.verify_inclusion(leaves[0], 4, 4, [], root)
    assert not merkle.verify_inclusion(leaves[0], -1, 4, [], root)


def test_building_a_proof_for_a_bad_index_raises() -> None:
    leaves = [merkle.leaf_hash(digest_str(i)) for i in range(4)]
    with pytest.raises(IndexError):
        merkle.inclusion_proof(leaves, 4)


def test_single_leaf_proof_is_empty() -> None:
    leaf = merkle.leaf_hash(digest_str(0))
    assert merkle.inclusion_proof([leaf], 0) == []
    assert merkle.verify_inclusion(leaf, 0, 1, [], leaf)


# ----------------------------------------------------------------------
# Wire form
# ----------------------------------------------------------------------


def test_format_and_parse_round_trip() -> None:
    raw = hashlib.sha256(b"anything").digest()
    formatted = merkle.format_hash(raw)

    assert formatted.startswith("sha256:")
    assert len(formatted) == len("sha256:") + 64
    assert merkle.parse_hash(formatted) == raw


def test_parse_rejects_an_unknown_algorithm() -> None:
    """The prefix exists so a second algorithm can be introduced without ambiguity
    about which one produced an existing row. Silently accepting an unprefixed value
    would defeat that."""
    with pytest.raises(ValueError, match="unsupported digest algorithm"):
        merkle.parse_hash("sha512:" + "ab" * 64)

    with pytest.raises(ValueError, match="unsupported digest algorithm"):
        merkle.parse_hash("ab" * 32)


def test_parse_rejects_a_wrong_length_digest() -> None:
    with pytest.raises(ValueError, match="expected 32 bytes"):
        merkle.parse_hash("sha256:" + "ab" * 16)


def test_split_point_is_the_largest_power_of_two_below_n() -> None:
    """The split is why left subtrees are complete, which is what keeps consistency
    proofs short. A midpoint split would still produce a valid tree — just not this one."""
    assert [merkle._split_point(n) for n in range(2, 18)] == [
        1,
        2,
        2,
        4,
        4,
        4,
        4,
        8,
        8,
        8,
        8,
        8,
        8,
        8,
        8,
        16,
    ]

    with pytest.raises(ValueError):
        merkle._split_point(1)
