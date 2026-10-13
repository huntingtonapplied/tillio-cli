"""Git repository parser — reads local .git to produce CommitSubmission data."""

import subprocess
import json
from typing import List, Dict, Any, Optional

from tillio_cli.log import logger


def run_git(args: List[str], cwd: Optional[str] = None) -> str:
    """Run a git command and return stdout."""
    logger.debug("git %s", " ".join(args))
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def get_repo_url(cwd: Optional[str] = None) -> str:
    """Get the remote origin URL."""
    try:
        url = run_git(["remote", "get-url", "origin"], cwd=cwd)
        # Normalize: git@github.com:user/repo.git -> github.com/user/repo
        if url.startswith("git@"):
            url = url.replace("git@", "").replace(":", "/", 1)
        url = url.removesuffix(".git")
        if url.startswith("https://"):
            url = url[len("https://"):]
        if url.startswith("http://"):
            url = url[len("http://"):]
        return url
    except RuntimeError:
        return ""


def get_branch(cwd: Optional[str] = None) -> str:
    """Get current branch name."""
    return run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)


def parse_commits(commit_range: str = "HEAD~1..HEAD", cwd: Optional[str] = None) -> List[Dict[str, Any]]:
    """Parse git log for a range of commits.

    Args:
        commit_range: Git revision range (e.g., HEAD~3..HEAD, abc123..def456, HEAD)
        cwd: Working directory

    Returns:
        List of commit dicts matching CommitSubmission schema
    """
    # Handle single ref (e.g., "HEAD") — treat as that single commit
    if ".." not in commit_range:
        commit_range = f"{commit_range}~1..{commit_range}"

    separator = "---TILLIO_COMMIT_SEP---"
    fmt = f"%H{separator}%s{separator}%b{separator}%an{separator}%ae{separator}%aI"

    log_output = run_git(
        ["log", f"--format={fmt}", "--reverse", commit_range],
        cwd=cwd,
    )

    if not log_output:
        return []

    commits = []
    for line in log_output.split("\n"):
        if not line.strip():
            continue
        parts = line.split(separator)
        if len(parts) < 6:
            continue

        sha = parts[0]
        subject = parts[1]
        body = parts[2]
        author_name = parts[3]
        author_email = parts[4]
        committed_at = parts[5]

        message = subject
        if body.strip():
            message = f"{subject}\n\n{body.strip()}"

        # Get diff stats for this commit
        additions, deletions, files_changed = _get_diff_stats(sha, cwd)

        commits.append({
            "sha": sha,
            "message": message,
            "author_name": author_name,
            "author_email": author_email,
            "committed_at": committed_at,
            "additions": additions,
            "deletions": deletions,
            "files_changed": files_changed,
        })

    return commits


def _get_diff_stats(sha: str, cwd: Optional[str] = None) -> tuple:
    """Get additions, deletions, and changed files for a commit."""
    try:
        numstat = run_git(["diff", "--numstat", f"{sha}~1..{sha}"], cwd=cwd)
    except RuntimeError:
        # First commit in repo has no parent
        try:
            numstat = run_git(["diff", "--numstat", "--root", sha], cwd=cwd)
        except RuntimeError:
            return 0, 0, []

    additions = 0
    deletions = 0
    files = []

    for line in numstat.split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            add = int(parts[0]) if parts[0] != "-" else 0
            delete = int(parts[1]) if parts[1] != "-" else 0
            additions += add
            deletions += delete
            files.append(parts[2])

    return additions, deletions, files


MAX_DIFF_BYTES = 50_000  # 50KB per commit diff


def get_diff_content(sha: str, cwd: Optional[str] = None) -> str:
    """Get unified diff for a commit, truncated to MAX_DIFF_BYTES."""
    try:
        diff = run_git(["diff", "-p", f"{sha}~1..{sha}"], cwd=cwd)
    except RuntimeError:
        try:
            diff = run_git(["diff", "-p", "--root", sha], cwd=cwd)
        except RuntimeError:
            return ""

    if len(diff.encode("utf-8", errors="replace")) > MAX_DIFF_BYTES:
        # Truncate at a line boundary
        truncated = diff.encode("utf-8", errors="replace")[:MAX_DIFF_BYTES].decode("utf-8", errors="replace")
        last_newline = truncated.rfind("\n")
        if last_newline > 0:
            truncated = truncated[:last_newline]
        return truncated + "\n... (diff truncated at 50KB)"

    return diff


def build_submission(commit_range: str = "HEAD~1..HEAD", cwd: Optional[str] = None) -> Dict[str, Any]:
    """Build a full CommitSubmission payload.

    Returns:
        Dict matching the CommitSubmission schema from CLI_ARCHITECTURE.md
    """
    return {
        "repository_url": get_repo_url(cwd),
        "branch": get_branch(cwd),
        "commits": parse_commits(commit_range, cwd),
    }
