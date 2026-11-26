"""Tests for vote ingestion module."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from governance.vote_ingest import (
    VoteProcessor,
    VoteSnapshotWriter,
    extract_nonce,
    extract_vote_choice,
    reaction_to_choice,
    sha256_hex_str,
    validate_vote_entry,
)
from governance.schema import VoteEntry, VOTE_CHOICES, VOTE_SOURCES


# ---------------------------------------------------------------------------
# Test extract_nonce
# ---------------------------------------------------------------------------


def test_extract_nonce_found():
    body = "Some text <!-- ballot:nonce:abc123 --> more text"
    assert extract_nonce(body) == "abc123"


def test_extract_nonce_not_found():
    body = "No nonce here"
    assert extract_nonce(body) is None


def test_extract_nonce_multiple():
    body = "<!-- ballot:nonce:first --> text <!-- ballot:nonce:second -->"
    # Should return first match
    assert extract_nonce(body) == "first"


def test_extract_nonce_with_spaces():
    body = "<!--   ballot:nonce:xyz789   -->"
    assert extract_nonce(body) == "xyz789"


# ---------------------------------------------------------------------------
# Test extract_vote_choice
# ---------------------------------------------------------------------------


def test_extract_vote_choice_approve():
    body = "My vote <!-- vote:approve -->"
    assert extract_vote_choice(body) == "approve"


def test_extract_vote_choice_reject():
    body = "I vote <!-- vote:reject -->"
    assert extract_vote_choice(body) == "reject"


def test_extract_vote_choice_abstain():
    body = "Abstaining <!-- vote:abstain -->"
    assert extract_vote_choice(body) == "abstain"


def test_extract_vote_choice_not_found():
    body = "No vote directive"
    assert extract_vote_choice(body) is None


def test_extract_vote_choice_invalid():
    body = "<!-- vote:invalid -->"
    assert extract_vote_choice(body) is None


# ---------------------------------------------------------------------------
# Test reaction_to_choice
# ---------------------------------------------------------------------------


def test_reaction_to_choice_approve():
    for reaction in ["+1", "thumbsup", "white_check_mark", "heavy_check_mark", "ballot_box_with_check"]:
        assert reaction_to_choice(reaction) == "approve"


def test_reaction_to_choice_reject():
    for reaction in ["-1", "thumbsdown", "x", "heavy_multiplication_x", "negative_squared_cross_mark"]:
        assert reaction_to_choice(reaction) == "reject"


def test_reaction_to_choice_abstain():
    for reaction in ["question", "grey_question"]:
        assert reaction_to_choice(reaction) == "abstain"


def test_reaction_to_choice_unknown():
    assert reaction_to_choice("heart") is None
    assert reaction_to_choice("rocket") is None


# ---------------------------------------------------------------------------
# Test sha256_hex_str
# ---------------------------------------------------------------------------


def test_sha256_hex_str():
    result = sha256_hex_str("test")
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)
    # Deterministic
    assert sha256_hex_str("test") == result


# ---------------------------------------------------------------------------
# Test VoteProcessor
# ---------------------------------------------------------------------------


def test_process_reactions_basic():
    processor = VoteProcessor("nonce-123", 100, 200)

    reactions = [
        {
            "id": 1001,
            "content": "+1",
            "user": {"id": 1001},
            "created_at": "2026-11-25T10:00:00Z",
        },
        {
            "id": 1002,
            "content": "-1",
            "user": {"id": 1002},
            "created_at": "2026-11-25T10:05:00Z",
        },
    ]

    raw_votes = processor.process_reactions(reactions, 500)

    assert len(raw_votes) == 2
    assert raw_votes[0].voter_gh_id == 1001
    assert raw_votes[0].choice == "approve"
    assert raw_votes[0].source == "reaction"
    assert raw_votes[1].voter_gh_id == 1002
    assert raw_votes[1].choice == "reject"


def test_process_reactions_deduplicates_latest():
    processor = VoteProcessor("nonce-123", 100, 200)

    reactions = [
        {
            "id": 1001,
            "content": "+1",
            "user": {"id": 1001},
            "created_at": "2026-11-25T10:00:00Z",
        },
        {
            "id": 1002,
            "content": "-1",
            "user": {"id": 1001},  # Same voter
            "created_at": "2026-11-25T10:05:00Z",  # Later
        },
    ]

    raw_votes = processor.process_reactions(reactions, 500)

    assert len(raw_votes) == 1
    assert raw_votes[0].voter_gh_id == 1001
    assert raw_votes[0].choice == "reject"  # Latest wins


def test_process_reactions_ignores_unknown():
    processor = VoteProcessor("nonce-123", 100, 200)

    reactions = [
        {
            "id": 1001,
            "content": "heart",
            "user": {"id": 1001},
            "created_at": "2026-11-25T10:00:00Z",
        },
        {
            "id": 1002,
            "content": "+1",
            "user": {"id": 1002},
            "created_at": "2026-11-25T10:05:00Z",
        },
    ]

    raw_votes = processor.process_reactions(reactions, 500)

    assert len(raw_votes) == 1
    assert raw_votes[0].voter_gh_id == 1002


def test_process_comments_with_nonce():
    processor = VoteProcessor("nonce-abc", 100, 200)

    comments = [
        {
            "id": 150,  # In window
            "user": {"id": 1001},
            "created_at": "2026-11-25T10:00:00Z",
            "updated_at": "2026-11-25T10:00:00Z",
            "body": "My vote <!-- ballot:nonce:nonce-abc --> <!-- vote:approve -->",
        },
        {
            "id": 151,  # In window
            "user": {"id": 1002},
            "created_at": "2026-11-25T10:05:00Z",
            "updated_at": "2026-11-25T10:05:00Z",
            "body": "I vote reject <!-- ballot:nonce:nonce-abc --> <!-- vote:reject -->",
        },
    ]

    raw_votes = processor.process_comments(comments)

    assert len(raw_votes) == 2
    assert raw_votes[0].voter_gh_id == 1001
    assert raw_votes[0].choice == "approve"
    assert raw_votes[0].source == "comment"
    assert raw_votes[1].voter_gh_id == 1002
    assert raw_votes[1].choice == "reject"


def test_process_comments_ignores_wrong_nonce():
    processor = VoteProcessor("nonce-abc", 100, 200)

    comments = [
        {
            "id": 150,  # In window
            "user": {"id": 1001},
            "created_at": "2026-11-25T10:00:00Z",
            "updated_at": "2026-11-25T10:00:00Z",
            "body": "My vote <!-- ballot:nonce:wrong-nonce --> <!-- vote:approve -->",
        },
        {
            "id": 151,  # In window
            "user": {"id": 1002},
            "created_at": "2026-11-25T10:05:00Z",
            "updated_at": "2026-11-25T10:05:00Z",
            "body": "My vote <!-- ballot:nonce:nonce-abc --> <!-- vote:reject -->",
        },
    ]

    raw_votes = processor.process_comments(comments)

    assert len(raw_votes) == 1
    assert raw_votes[0].voter_gh_id == 1002


def test_process_comments_deduplicates_by_updated_at():
    processor = VoteProcessor("nonce-abc", 100, 200)

    comments = [
        {
            "id": 150,  # In window
            "user": {"id": 1001},
            "created_at": "2026-11-25T10:00:00Z",
            "updated_at": "2026-11-25T10:00:00Z",
            "body": "Vote <!-- ballot:nonce:nonce-abc --> <!-- vote:approve -->",
        },
        {
            "id": 151,  # In window
            "user": {"id": 1001},  # Same voter
            "created_at": "2026-11-25T10:05:00Z",
            "updated_at": "2026-11-25T10:10:00Z",  # Later updated_at
            "body": "Changed my mind <!-- ballot:nonce:nonce-abc --> <!-- vote:reject -->",
        },
    ]

    raw_votes = processor.process_comments(comments)

    assert len(raw_votes) == 1
    assert raw_votes[0].voter_gh_id == 1001
    assert raw_votes[0].choice == "reject"  # Latest updated_at wins


def test_process_comments_filters_by_time_window():
    processor = VoteProcessor("nonce-abc", 100, 200)

    comments = [
        {
            "id": 50,  # Before open
            "user": {"id": 1001},
            "created_at": "2026-11-25T09:00:00Z",
            "updated_at": "2026-11-25T09:00:00Z",
            "body": "Early vote <!-- ballot:nonce:nonce-abc --> <!-- vote:approve -->",
        },
        {
            "id": 150,  # In window
            "user": {"id": 1002},
            "created_at": "2026-11-25T10:00:00Z",
            "updated_at": "2026-11-25T10:00:00Z",
            "body": "In window <!-- ballot:nonce:nonce-abc --> <!-- vote:reject -->",
        },
        {
            "id": 250,  # After close
            "user": {"id": 1003},
            "created_at": "2026-11-25T12:00:00Z",
            "updated_at": "2026-11-25T12:00:00Z",
            "body": "Late vote <!-- ballot:nonce:nonce-abc --> <!-- vote:abstain -->",
        },
    ]

    raw_votes = processor.process_comments(comments)

    assert len(raw_votes) == 1
    assert raw_votes[0].voter_gh_id == 1002


# ---------------------------------------------------------------------------
# Test VoteEntry validation
# ---------------------------------------------------------------------------


def test_validate_vote_entry_valid():
    entry = VoteEntry(
        voter_gh_id=1001,
        choice="approve",
        comment_id=1001,
        created_at="2026-11-25T10:00:00Z",
        updated_at="2026-11-25T10:00:00Z",
        body_sha256="a" * 64,
        source="reaction",
    )
    validate_vote_entry(entry)  # Should not raise


def test_validate_vote_entry_invalid_choice():
    entry = VoteEntry(
        voter_gh_id=1001,
        choice="invalid",
        comment_id=1001,
        created_at="2026-11-25T10:00:00Z",
        updated_at="2026-11-25T10:00:00Z",
        body_sha256="a" * 64,
        source="reaction",
    )
    with pytest.raises(ValueError, match="Invalid choice"):
        validate_vote_entry(entry)


def test_validate_vote_entry_invalid_source():
    entry = VoteEntry(
        voter_gh_id=1001,
        choice="approve",
        comment_id=1001,
        created_at="2026-11-25T10:00:00Z",
        updated_at="2026-11-25T10:00:00Z",
        body_sha256="a" * 64,
        source="invalid",
    )
    with pytest.raises(ValueError, match="Invalid source"):
        validate_vote_entry(entry)


def test_validate_vote_entry_invalid_voter_id():
    entry = VoteEntry(
        voter_gh_id=0,
        choice="approve",
        comment_id=1001,
        created_at="2026-11-25T10:00:00Z",
        updated_at="2026-11-25T10:00:00Z",
        body_sha256="a" * 64,
        source="reaction",
    )
    with pytest.raises(ValueError, match="voter_gh_id must be a positive integer"):
        validate_vote_entry(entry)


def test_validate_vote_entry_invalid_comment_id():
    entry = VoteEntry(
        voter_gh_id=1001,
        choice="approve",
        comment_id=-1,
        created_at="2026-11-25T10:00:00Z",
        updated_at="2026-11-25T10:00:00Z",
        body_sha256="a" * 64,
        source="reaction",
    )
    with pytest.raises(ValueError, match="comment_id must be a positive integer"):
        validate_vote_entry(entry)


def test_validate_vote_entry_invalid_body_sha256():
    entry = VoteEntry(
        voter_gh_id=1001,
        choice="approve",
        comment_id=1001,
        created_at="2026-11-25T10:00:00Z",
        updated_at="2026-11-25T10:00:00Z",
        body_sha256="short",
        source="reaction",
    )
    with pytest.raises(ValueError, match="body_sha256 must be 64 hex characters"):
        validate_vote_entry(entry)


# ---------------------------------------------------------------------------
# Test VoteSnapshotWriter
# ---------------------------------------------------------------------------


def test_write_snapshot():
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = VoteSnapshotWriter(tmpdir)

        entries = [
            VoteEntry(
                voter_gh_id=1001,
                choice="approve",
                comment_id=1001,
                created_at="2026-11-25T10:00:00Z",
                updated_at="2026-11-25T10:00:00Z",
                body_sha256="a" * 64,
                source="reaction",
            ),
            VoteEntry(
                voter_gh_id=1002,
                choice="reject",
                comment_id=1002,
                created_at="2026-11-25T10:05:00Z",
                updated_at="2026-11-25T10:05:00Z",
                body_sha256="b" * 64,
                source="comment",
            ),
        ]

        snapshot = writer.write_snapshot("dec-2026-0001", entries, "2026-11-25T10:00:00Z")

        assert snapshot.decision_id == "dec-2026-0001"
        assert len(snapshot.votes) == 2
        assert len(snapshot.snapshot_hash) == 64

        # Verify file exists and has correct content
        output_path = Path(tmpdir) / "dec-2026-0001.json"
        assert output_path.exists()

        with open(output_path) as f:
            data = json.load(f)
        assert len(data) == 2
        # Should be sorted by voter_gh_id
        assert data[0]["voter_gh_id"] == 1001
        assert data[1]["voter_gh_id"] == 1002


def test_write_snapshot_deterministic_hash():
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = VoteSnapshotWriter(tmpdir)

        entries = [
            VoteEntry(
                voter_gh_id=1001,
                choice="approve",
                comment_id=1001,
                created_at="2026-11-25T10:00:00Z",
                updated_at="2026-11-25T10:00:00Z",
                body_sha256="a" * 64,
                source="reaction",
            ),
        ]

        snapshot1 = writer.write_snapshot("dec-2026-0001", entries, "2026-11-25T10:00:00Z")
        snapshot2 = writer.write_snapshot("dec-2026-0001", entries, "2026-11-25T10:00:00Z")

        assert snapshot1.snapshot_hash == snapshot2.snapshot_hash


def test_write_snapshot_sorts_by_voter_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = VoteSnapshotWriter(tmpdir)

        entries = [
            VoteEntry(
                voter_gh_id=1003,
                choice="approve",
                comment_id=1003,
                created_at="2026-11-25T10:00:00Z",
                updated_at="2026-11-25T10:00:00Z",
                body_sha256="c" * 64,
                source="reaction",
            ),
            VoteEntry(
                voter_gh_id=1001,
                choice="reject",
                comment_id=1001,
                created_at="2026-11-25T10:00:00Z",
                updated_at="2026-11-25T10:00:00Z",
                body_sha256="a" * 64,
                source="reaction",
            ),
            VoteEntry(
                voter_gh_id=1002,
                choice="abstain",
                comment_id=1002,
                created_at="2026-11-25T10:00:00Z",
                updated_at="2026-11-25T10:00:00Z",
                body_sha256="b" * 64,
                source="reaction",
            ),
        ]

        snapshot = writer.write_snapshot("dec-2026-0001", entries, "2026-11-25T10:00:00Z")

        output_path = Path(tmpdir) / "dec-2026-0001.json"
        with open(output_path) as f:
            data = json.load(f)

        assert data[0]["voter_gh_id"] == 1001
        assert data[1]["voter_gh_id"] == 1002
        assert data[2]["voter_gh_id"] == 1003


# ---------------------------------------------------------------------------
# Test integration with ledger votes_snapshot_hash
# ---------------------------------------------------------------------------


def test_snapshot_hash_matches_ledger():
    """Verify our snapshot hash matches the ledger's votes_snapshot_hash."""
    from governance.ledger import votes_snapshot_hash as ledger_votes_snapshot_hash

    with tempfile.TemporaryDirectory() as tmpdir:
        writer = VoteSnapshotWriter(tmpdir)

        # Use the test vector from LEDGER-FORMAT.md
        entries = [
            VoteEntry(
                voter_gh_id=1001,
                choice="approve",  # choice not in snapshot but in VoteEntry
                comment_id=191234701,
                created_at="2026-11-23T10:00:00.000Z",
                updated_at="2026-11-23T10:00:00.000Z",
                body_sha256="ab" * 32,
                source="reaction",
            ),
        ]

        snapshot = writer.write_snapshot("dec-2026-0001", entries, "2026-11-23T10:00:00Z")

        # Load the written file and compute hash via ledger function
        output_path = Path(tmpdir) / "dec-2026-0001.json"
        with open(output_path) as f:
            votes_data = json.load(f)

        ledger_hash = ledger_votes_snapshot_hash(votes_data)

        assert snapshot.snapshot_hash == ledger_hash
        # Should match the published vector
        assert snapshot.snapshot_hash == "fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])