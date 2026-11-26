"""Vote ingestion for The Ultimate Dream governance.

Read-only over GitHub comments/reactions. Never authors a vote.
Snapshot at close: comment_id+author+created_at+updated_at+body_sha256 -> votes/<decision_id>.json,
hashed into ballot_snapshot_hash. Source field: reaction default, nonced comment for multi-choice.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from governance.ledger import canonical_bytes, votes_snapshot_hash
from governance.schema import VoteEntry, VOTE_CHOICES, VOTE_SOURCES


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Reaction to choice mapping (GitHub emoji names)
REACTION_TO_CHOICE = {
    "+1": "approve",
    "thumbsup": "approve",
    "-1": "reject",
    "thumbsdown": "reject",
    "white_check_mark": "approve",
    "x": "reject",
    "heavy_check_mark": "approve",
    "heavy_multiplication_x": "reject",
    "ballot_box_with_check": "approve",
    "negative_squared_cross_mark": "reject",
    "question": "abstain",
    "grey_question": "abstain",
}

# Valid vote choices
VALID_CHOICES = set(VOTE_CHOICES)
VALID_SOURCES = set(VOTE_SOURCES)

# Nonce pattern for multi-choice votes: <!-- ballot:nonce:... -->
NONCE_PATTERN = re.compile(r"<!--\s*ballot:nonce:([a-zA-Z0-9_-]+)\s*-->")

# Vote pattern for nonced comments: <!-- vote:approve|reject|abstain -->
VOTE_PATTERN = re.compile(r"<!--\s*vote:(approve|reject|abstain)\s*-->")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawVote:
    """Raw vote data from GitHub before normalization."""

    voter_gh_id: int
    choice: str
    comment_id: int
    created_at: str
    updated_at: str
    body_sha256: str
    source: str


@dataclass(frozen=True)
class VoteSnapshot:
    """Frozen vote snapshot ready for persistence."""

    decision_id: str
    votes: list[VoteEntry]
    snapshot_hash: str
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    """Compute SHA256 hex digest."""
    return hashlib.sha256(data).hexdigest()


def sha256_hex_str(text: str) -> str:
    """Compute SHA256 hex digest of a UTF-8 string."""
    return sha256_hex(text.encode("utf-8"))


def extract_nonce(body: str) -> str | None:
    """Extract ballot nonce from a comment body.

    The nonce is embedded as an HTML comment: <!-- ballot:nonce:abc123 -->
    """
    match = NONCE_PATTERN.search(body)
    return match.group(1) if match else None


def extract_vote_choice(body: str) -> str | None:
    """Extract vote choice from a nonced comment body.

    The vote is embedded as an HTML comment: <!-- vote:approve -->
    """
    match = VOTE_PATTERN.search(body)
    return match.group(1) if match else None


def reaction_to_choice(reaction_name: str) -> str | None:
    """Map a GitHub reaction name to a vote choice."""
    return REACTION_TO_CHOICE.get(reaction_name.lower())


def validate_vote_entry(entry: VoteEntry) -> None:
    """Validate a VoteEntry against schema constraints."""
    if entry.choice not in VALID_CHOICES:
        raise ValueError(f"Invalid choice: {entry.choice}. Must be one of {VALID_CHOICES}")
    if entry.source not in VALID_SOURCES:
        raise ValueError(f"Invalid source: {entry.source}. Must be one of {VALID_SOURCES}")
    if not isinstance(entry.voter_gh_id, int) or entry.voter_gh_id <= 0:
        raise ValueError("voter_gh_id must be a positive integer")
    if not isinstance(entry.comment_id, int) or entry.comment_id <= 0:
        raise ValueError("comment_id must be a positive integer")
    if len(entry.body_sha256) != 64:
        raise ValueError("body_sha256 must be 64 hex characters")


# ---------------------------------------------------------------------------
# GitHub API Client
# ---------------------------------------------------------------------------


class GitHubVoteClient:
    """Read-only GitHub API client for fetching votes from comments/reactions.

    stdlib only — urllib, not aiohttp. This repo carries no third-party HTTP
    dependency, and a hidden one makes the module unimportable anywhere that
    has not installed it.
    """

    def __init__(self, token: str, repo_owner: str, repo_name: str, timeout: float = 30.0):
        self.token = token
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.timeout = timeout
        self.base_url = "https://api.github.com"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def _paginate(self, url: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            chunk = self._get(url, {"page": page, "per_page": 100}) or []
            if not chunk:
                break
            items.extend(chunk)
            if len(chunk) < 100:
                break
            page += 1
        return items

    def fetch_issue_comments(self, issue_number: int) -> list[dict[str, Any]]:
        """Fetch all comments on an issue (paginated)."""
        url = f"{self.base_url}/repos/{self.repo_owner}/{self.repo_name}/issues/{issue_number}/comments"
        return self._paginate(url)

    def fetch_comment_reactions(self, comment_id: int) -> list[dict[str, Any]]:
        """Fetch all reactions on a comment (paginated)."""
        url = f"{self.base_url}/repos/{self.repo_owner}/{self.repo_name}/issues/comments/{comment_id}/reactions"
        return self._paginate(url)

    def fetch_single_comment(self, comment_id: int) -> dict[str, Any] | None:
        """Fetch a single comment by ID."""
        url = f"{self.base_url}/repos/{self.repo_owner}/{self.repo_name}/issues/comments/{comment_id}"
        return self._get(url)


# ---------------------------------------------------------------------------
# Vote Processing
# ---------------------------------------------------------------------------


class VoteProcessor:
    """Processes raw GitHub comments/reactions into normalized VoteEntry objects."""

    def __init__(self, ballot_nonce: str, open_comment_id: int, close_comment_id: int):
        self.ballot_nonce = ballot_nonce
        self.open_comment_id = open_comment_id
        self.close_comment_id = close_comment_id

    def process_reactions(
        self, reactions: list[dict[str, Any]], ballot_comment_id: int
    ) -> list[RawVote]:
        """Process reactions on the ballot comment into raw votes."""
        votes = []
        seen_voters: dict[int, RawVote] = {}

        for reaction in reactions:
            choice = reaction_to_choice(reaction.get("content", ""))
            if not choice:
                continue

            user = reaction.get("user", {})
            voter_gh_id = user.get("id")
            if not voter_gh_id:
                continue

            comment_id = reaction.get("id")
            created_at = reaction.get("created_at")
            # Reactions don't have updated_at, use created_at
            updated_at = created_at

            # Body SHA for reactions is hash of the reaction content (deterministic)
            body_sha256 = sha256_hex_str(f"reaction:{reaction.get('content', '')}")

            raw = RawVote(
                voter_gh_id=voter_gh_id,
                choice=choice,
                comment_id=comment_id,
                created_at=created_at,
                updated_at=updated_at,
                body_sha256=body_sha256,
                source="reaction",
            )

            # Latest valid entry per voter counts
            if voter_gh_id not in seen_voters or raw.created_at > seen_voters[voter_gh_id].created_at:
                seen_voters[voter_gh_id] = raw

        return list(seen_voters.values())

    def process_comments(
        self, comments: list[dict[str, Any]]
    ) -> list[RawVote]:
        """Process nonced comments into raw votes."""
        votes = []
        seen_voters: dict[int, RawVote] = {}

        for comment in comments:
            # Only process comments between open and close (inclusive) by comment ID
            comment_id = comment.get("id")
            if not comment_id:
                continue
            if comment_id < self.open_comment_id or comment_id > self.close_comment_id:
                continue  # Outside the ballot window

            # Check if comment has the ballot nonce
            body = comment.get("body", "")
            nonce = extract_nonce(body)
            if nonce != self.ballot_nonce:
                continue  # Not a vote comment for this ballot

            # Extract vote choice
            choice = extract_vote_choice(body)
            if not choice:
                continue  # No valid vote directive

            user = comment.get("user", {})
            voter_gh_id = user.get("id")
            if not voter_gh_id:
                continue

            created_at = comment.get("created_at")
            updated_at = comment.get("updated_at", created_at)
            body_sha256 = sha256_hex_str(body)

            raw = RawVote(
                voter_gh_id=voter_gh_id,
                choice=choice,
                comment_id=comment_id,
                created_at=created_at,
                updated_at=updated_at,
                body_sha256=body_sha256,
                source="comment",
            )

            # Latest valid entry per voter counts (updated_at is server-side)
            if voter_gh_id not in seen_voters or raw.updated_at > seen_voters[voter_gh_id].updated_at:
                seen_voters[voter_gh_id] = raw

        return list(seen_voters.values())

    def to_vote_entries(self, raw_votes: list[RawVote]) -> list[VoteEntry]:
        """Convert raw votes to validated VoteEntry objects."""
        entries = []
        for raw in raw_votes:
            entry = VoteEntry(
                voter_gh_id=raw.voter_gh_id,
                choice=raw.choice,
                comment_id=raw.comment_id,
                created_at=raw.created_at,
                updated_at=raw.updated_at,
                body_sha256=raw.body_sha256,
                source=raw.source,
            )
            validate_vote_entry(entry)
            entries.append(entry)
        return entries

    @staticmethod
    def to_snapshot_dicts(vote_entries: list[VoteEntry]) -> list[dict[str, Any]]:
        """Convert VoteEntry objects to minimal dicts for snapshot hashing.

        The frozen snapshot only includes: voter_gh_id, comment_id, created_at,
        updated_at, body_sha256 (no choice, no source).
        """
        return [
            {
                "voter_gh_id": v.voter_gh_id,
                "comment_id": v.comment_id,
                "created_at": v.created_at,
                "updated_at": v.updated_at,
                "body_sha256": v.body_sha256,
            }
            for v in vote_entries
        ]


# ---------------------------------------------------------------------------
# Snapshot Writer
# ---------------------------------------------------------------------------


class VoteSnapshotWriter:
    """Writes frozen vote snapshots to votes/<decision_id>.json."""

    def __init__(self, votes_dir: str | Path):
        self.votes_dir = Path(votes_dir)
        self.votes_dir.mkdir(parents=True, exist_ok=True)

    def write_snapshot(
        self,
        decision_id: str,
        vote_entries: list[VoteEntry],
        close_comment_created_at: str,
    ) -> VoteSnapshot:
        """Write a frozen vote snapshot and return metadata."""
        # Sort votes by voter_gh_id for deterministic ordering
        sorted_entries = sorted(vote_entries, key=lambda v: v.voter_gh_id)

        # Convert to minimal dict list for canonical hashing (no choice, no source)
        votes_dicts = VoteProcessor.to_snapshot_dicts(sorted_entries)

        # Compute snapshot hash
        snapshot_hash = votes_snapshot_hash(votes_dicts)

        # Create snapshot object
        snapshot = VoteSnapshot(
            decision_id=decision_id,
            votes=sorted_entries,
            snapshot_hash=snapshot_hash,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        )

        # Write to file
        output_path = self.votes_dir / f"{decision_id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(votes_dicts, f, separators=(",", ":"), ensure_ascii=False)

        return snapshot


# ---------------------------------------------------------------------------
# High-level Ingestion Function
# ---------------------------------------------------------------------------


def ingest_votes(
    *,
    token: str,
    repo_owner: str,
    repo_name: str,
    issue_number: int,
    ballot_nonce: str,
    open_comment_id: int,
    close_comment_id: int,
    decision_id: str,
    votes_dir: str | Path,
    ballot_comment_id: int | None = None,
) -> VoteSnapshot:
    """Full vote ingestion pipeline.

    Args:
        token: GitHub token (read-only scope sufficient)
        repo_owner: Repository owner
        repo_name: Repository name
        issue_number: Issue number where ballot lives
        ballot_nonce: The nonce published at ballot open
        open_comment_id: The ballot open comment ID
        close_comment_id: The ballot close comment ID
        decision_id: Decision ID for the snapshot filename
        votes_dir: Directory to write votes/<decision_id>.json
        ballot_comment_id: The pinned ballot comment ID (for reactions). If None, uses open_comment_id.

    Returns:
        VoteSnapshot with the frozen votes and hash.
    """
    # Use open_comment_id as ballot comment if not specified
    if ballot_comment_id is None:
        ballot_comment_id = open_comment_id

    client = GitHubVoteClient(token, repo_owner, repo_name)
    processor = VoteProcessor(ballot_nonce, open_comment_id, close_comment_id)
    writer = VoteSnapshotWriter(votes_dir)

    # Fetch all comments on the issue
    comments = client.fetch_issue_comments(issue_number)

    # Filter comments to those between open and close (inclusive)
    relevant_comments = [
        c for c in comments
        if open_comment_id <= c.get("id", 0) <= close_comment_id
    ]

    # Process nonced comments
    comment_votes = processor.process_comments(relevant_comments)

    # Fetch reactions on the ballot comment
    reactions = client.fetch_comment_reactions(ballot_comment_id)

    # Process reactions
    reaction_votes = processor.process_reactions(reactions, ballot_comment_id)

    # Combine: comment votes take precedence for multi-choice, reactions for default
    # But per spec: "source: reaction default, nonced comment for multi-choice"
    # So we keep both sources, deduplicating by voter (latest valid entry wins)
    all_raw_votes = comment_votes + reaction_votes

    # Deduplicate by voter: latest updated_at wins
    seen: dict[int, RawVote] = {}
    for raw in all_raw_votes:
        if raw.voter_gh_id not in seen or raw.updated_at > seen[raw.voter_gh_id].updated_at:
            seen[raw.voter_gh_id] = raw

    # Convert to VoteEntry objects
    vote_entries = processor.to_vote_entries(list(seen.values()))

    # Write snapshot
    snapshot = writer.write_snapshot(decision_id, vote_entries, close_comment_id)

    return snapshot


# ---------------------------------------------------------------------------
# CLI for testing
# ---------------------------------------------------------------------------


def _main() -> None:
    """CLI entry point for testing."""
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Ingest votes from GitHub")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--repo-owner", required=True)
    parser.add_argument("--repo-name", required=True)
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--ballot-nonce", required=True)
    parser.add_argument("--open-comment-id", type=int, required=True)
    parser.add_argument("--close-comment-id", type=int, required=True)
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--votes-dir", default="votes")
    parser.add_argument("--ballot-comment-id", type=int)
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("GITHUB_TOKEN required")

    snapshot = ingest_votes(
        token=args.token,
        repo_owner=args.repo_owner,
        repo_name=args.repo_name,
        issue_number=args.issue_number,
        ballot_nonce=args.ballot_nonce,
        open_comment_id=args.open_comment_id,
        close_comment_id=args.close_comment_id,
        decision_id=args.decision_id,
        votes_dir=args.votes_dir,
        ballot_comment_id=args.ballot_comment_id,
    )

    print(f"Snapshot written: votes/{args.decision_id}.json")
    print(f"Votes: {len(snapshot.votes)}")
    print(f"Snapshot hash: {snapshot.snapshot_hash}")


if __name__ == "__main__":
    _main()