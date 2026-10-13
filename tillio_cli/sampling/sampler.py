"""FileSampler — intelligent file selection for bulk repo evaluation.

Scans a repository, classifies its size, selects a sampling strategy,
scores files by priority, and returns ranked files within a token budget.
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Optional

from tillio_cli.sampling.constants import (
    CODE_EXTS, SKIP_DIRS, KEY_DIRS, ENTRY_POINT_NAMES,
    CONFIG_EXTS, CONFIG_NAMES,
    TIER_THRESHOLDS, TIER_TOKEN_BUDGETS, TIER_STRATEGIES,
    WEIGHT_RECENCY, WEIGHT_KEY_DIR, WEIGHT_IMPORTS,
    WEIGHT_ENTRY_POINT, WEIGHT_SIZE,
    PENALTY_TEST, PENALTY_CONFIG,
    MAX_FILE_SIZE_BYTES, RECENT_COMMITS_LOOKBACK,
    CHARS_PER_TOKEN,
    RepoSizeTier, SamplingStrategy,
)
from tillio_cli.sampling.budget import BudgetTracker

logger = logging.getLogger(__name__)


# ======================================================================
# Data classes
# ======================================================================

@dataclass
class FileInfo:
    """Metadata about a single scoreable file (content not yet loaded)."""
    path: str
    ext: str
    size_bytes: int
    lines: int
    dir_depth: int
    last_modified_commit: Optional[int] = None  # commits ago (0 = most recent)
    has_test: bool = False
    import_count: int = 0  # how many other files import this one
    is_entry_point: bool = False
    is_config: bool = False
    is_test: bool = False


@dataclass
class ScoredFile:
    """A file selected for evaluation, with content loaded and priority assigned."""
    info: FileInfo
    content: str
    priority: float
    tokens_est: int
    reason: str  # why this file was selected


@dataclass
class SampleResult:
    """Output of FileSampler.sample()."""
    files: list[ScoredFile]
    tier: RepoSizeTier
    strategy: SamplingStrategy
    total_files_scanned: int
    total_lines_scanned: int
    token_budget: int
    tokens_used: int
    languages: dict = field(default_factory=dict)  # ext -> LOC
    top_directories: list = field(default_factory=list)  # top dirs by LOC


# ======================================================================
# FileSampler
# ======================================================================

class FileSampler:
    """Scans a repo and selects files for LLM evaluation within a token budget.

    Usage:
        sampler = FileSampler(repo_root="/path/to/repo")
        result = sampler.sample(targets=["src/", "lib/"])
    """

    def __init__(self, repo_root: str, cwd: Optional[str] = None):
        self.repo_root = os.path.abspath(repo_root)
        self.cwd = cwd or self.repo_root

    def sample(self, targets: Optional[list[str]] = None, recursive: bool = True) -> SampleResult:
        """Run the full sampling pipeline.

        Args:
            targets: Specific paths to scope the scan to. If None, scans entire repo.
            recursive: Whether to recurse into subdirectories. Default True.

        Returns:
            SampleResult with ranked, budget-constrained files ready for evaluation.
        """
        # 1. Scan — build FileIndex
        file_index = self._scan(targets, recursive=recursive)
        if not file_index:
            return SampleResult(
                files=[], tier=RepoSizeTier.SMALL,
                strategy=SamplingStrategy.ALL,
                total_files_scanned=0, total_lines_scanned=0,
                token_budget=0, tokens_used=0,
            )

        # 2. Classify — determine tier
        total_lines = sum(f.lines for f in file_index)
        tier = self._classify_tier(total_lines)
        strategy = TIER_STRATEGIES[tier]
        budget_tokens = TIER_TOKEN_BUDGETS[tier]

        logger.info(
            "Repo scan: %d files, %d lines → tier=%s, strategy=%s, budget=%d tokens",
            len(file_index), total_lines, tier.value, strategy.value, budget_tokens,
        )

        # 3. Enrich — add recency and import counts (skip for SMALL)
        if tier != RepoSizeTier.SMALL:
            self._enrich_recency(file_index)
        if tier in (RepoSizeTier.MEDIUM, RepoSizeTier.LARGE):
            self._enrich_import_counts(file_index)

        # 4. Score — compute priority for every file
        scored_index = [(f, self._score_file(f, strategy)) for f in file_index]
        scored_index.sort(key=lambda x: x[1], reverse=True)

        # 5. Select — fill budget from top of ranked list
        tracker = BudgetTracker(budget_tokens)
        selected = self._select_files(scored_index, tracker, strategy)

        # 6. Compute summary stats
        languages = {}
        dir_loc = {}
        for f in file_index:
            languages[f.ext] = languages.get(f.ext, 0) + f.lines
            top_dir = f.path.split(os.sep)[0] if os.sep in f.path else "."
            dir_loc[top_dir] = dir_loc.get(top_dir, 0) + f.lines
        top_dirs = sorted(dir_loc, key=dir_loc.get, reverse=True)[:10]

        return SampleResult(
            files=selected,
            tier=tier,
            strategy=strategy,
            total_files_scanned=len(file_index),
            total_lines_scanned=total_lines,
            token_budget=budget_tokens,
            tokens_used=tracker.used,
            languages=languages,
            top_directories=top_dirs,
        )

    # ==================================================================
    # Step 1: Scan
    # ==================================================================

    def _scan(self, targets: Optional[list[str]] = None, recursive: bool = True) -> list[FileInfo]:
        """Walk the file system and build a FileIndex of scoreable files."""
        scan_roots = []
        if targets:
            for t in targets:
                full = os.path.join(self.repo_root, t) if not os.path.isabs(t) else t
                if os.path.exists(full):
                    scan_roots.append(full)
        if not scan_roots:
            scan_roots = [self.repo_root]

        index = []
        seen_paths = set()

        for root_path in scan_roots:
            if os.path.isfile(root_path):
                info = self._file_info(root_path)
                if info and info.path not in seen_paths:
                    seen_paths.add(info.path)
                    index.append(info)
                continue

            for dirpath, dirnames, filenames in os.walk(root_path):
                # Prune skip dirs
                dirnames[:] = [
                    d for d in dirnames
                    if not d.startswith(".") and d not in SKIP_DIRS
                ]

                for fname in filenames:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in CODE_EXTS:
                        continue
                    fpath = os.path.join(dirpath, fname)
                    info = self._file_info(fpath)
                    if info and info.path not in seen_paths:
                        seen_paths.add(info.path)
                        index.append(info)

                if not recursive:
                    break  # only top-level of each target directory

        return index

    def _file_info(self, fpath: str) -> Optional[FileInfo]:
        """Build a FileInfo for a single file. Returns None if unreadable/too large."""
        try:
            size = os.path.getsize(fpath)
            if size > MAX_FILE_SIZE_BYTES or size == 0:
                return None

            rel = os.path.relpath(fpath, self.repo_root)
            ext = os.path.splitext(fpath)[1].lower()
            basename = os.path.basename(fpath).lower()

            # Quick line count without reading full content
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                lines = sum(1 for _ in f)

            depth = rel.count(os.sep)

            # Classify file type
            is_test = _is_test_file(rel, basename)
            is_entry = basename in ENTRY_POINT_NAMES
            is_config = ext in CONFIG_EXTS or basename in CONFIG_NAMES

            return FileInfo(
                path=rel,
                ext=ext,
                size_bytes=size,
                lines=lines,
                dir_depth=depth,
                is_entry_point=is_entry,
                is_config=is_config,
                is_test=is_test,
            )
        except (OSError, UnicodeDecodeError):
            return None

    # ==================================================================
    # Step 2: Classify
    # ==================================================================

    def _classify_tier(self, total_lines: int) -> RepoSizeTier:
        """Determine repo size tier from total scoreable lines."""
        if total_lines < TIER_THRESHOLDS[RepoSizeTier.SMALL]:
            return RepoSizeTier.SMALL
        elif total_lines < TIER_THRESHOLDS[RepoSizeTier.MEDIUM]:
            return RepoSizeTier.MEDIUM
        elif total_lines < TIER_THRESHOLDS[RepoSizeTier.LARGE]:
            return RepoSizeTier.LARGE
        else:
            return RepoSizeTier.HUGE

    # ==================================================================
    # Step 3: Enrich
    # ==================================================================

    def _enrich_recency(self, index: list[FileInfo]) -> None:
        """Tag each file with how recently it was modified (commits ago).

        Uses git log to find files changed in the last N commits.
        Files not found in recent history get last_modified_commit=None.
        """
        try:
            from tillio_cli.git import run_git
            output = run_git(
                ["log", f"--pretty=format:", "--name-only",
                 f"-n{RECENT_COMMITS_LOOKBACK}"],
                cwd=self.cwd,
            )
        except (RuntimeError, ImportError):
            return

        # Build recency map: file_path -> lowest commit index it appeared in
        recency_map: dict[str, int] = {}
        commit_index = 0
        for line in output.splitlines():
            if not line.strip():
                commit_index += 1
                continue
            path = line.strip()
            if path not in recency_map:
                recency_map[path] = commit_index

        # Apply to index
        for f in index:
            if f.path in recency_map:
                f.last_modified_commit = recency_map[f.path]

    def _enrich_import_counts(self, index: list[FileInfo]) -> None:
        """Count inbound imports for each file (how many others import it).

        REVISIT: This uses a simple basename grep which can produce false
        positives for common names (e.g., "utils", "index"). A more precise
        approach would parse actual import paths, but that's expensive for
        large repos. Monitor false positive rates in practice.
        """
        basename_to_files: dict[str, list[FileInfo]] = {}
        for f in index:
            name = os.path.splitext(os.path.basename(f.path))[0]
            # Skip very common names that would match everything
            if name in ("index", "__init__", "utils", "helpers", "types", "constants"):
                continue
            basename_to_files.setdefault(name, []).append(f)

        try:
            from tillio_cli.git import run_git
            for name, files in basename_to_files.items():
                # Collect the paths of files with this basename so we can
                # exclude self-imports (a file importing itself)
                own_paths = {f.path for f in files}
                try:
                    output = run_git(
                        ["grep", "-c", "-E",
                         f"from.*{name}.*import|import.*{name}|require.*{name}",
                         "--", "*.py", "*.ts", "*.tsx", "*.js", "*.jsx"],
                        cwd=self.cwd,
                    )
                    # Output: "file.py:3" (file:count)
                    count = 0
                    for line in output.splitlines():
                        parts = line.rsplit(":", 1)
                        if len(parts) == 2 and parts[0] not in own_paths:
                            try:
                                count += int(parts[1])
                            except ValueError:
                                pass
                    for f in files:
                        f.import_count = count
                except RuntimeError:
                    # git grep returns non-zero if no matches
                    pass
        except ImportError:
            pass

    # ==================================================================
    # Step 4: Score
    # ==================================================================

    def _score_file(self, f: FileInfo, strategy: SamplingStrategy) -> float:
        """Compute priority score for a file.

        REVISIT: Priority weights are initial estimates. After running bulk
        evals, compare LLM output quality from priority-sampled vs random
        files and adjust weights in constants.py.
        """
        score = 0.0

        # Recency: files changed recently are more relevant
        if f.last_modified_commit is not None:
            recency = max(0.0, 1.0 - (f.last_modified_commit / RECENT_COMMITS_LOOKBACK))
            score += recency * WEIGHT_RECENCY

        # Key directory
        if _is_key_directory(f.path):
            score += WEIGHT_KEY_DIR

        # Import count (dependency weight)
        if f.import_count > 0:
            score += min(f.import_count / 10, 1.0) * WEIGHT_IMPORTS

        # Entry point
        if f.is_entry_point:
            score += WEIGHT_ENTRY_POINT

        # Size: prefer medium-sized files (most informative per token)
        if 10 < f.lines < 500:
            score += WEIGHT_SIZE
        elif f.lines >= 500:
            score += WEIGHT_SIZE * 0.5

        # Penalties
        if f.is_test:
            score *= PENALTY_TEST
        if f.is_config and not f.is_entry_point:
            score *= PENALTY_CONFIG

        return round(score, 4)

    # ==================================================================
    # Step 5: Select
    # ==================================================================

    def _select_files(
        self,
        scored_index: list[tuple[FileInfo, float]],
        tracker: BudgetTracker,
        strategy: SamplingStrategy,
    ) -> list[ScoredFile]:
        """Read file contents and select files within token budget.

        Files are already sorted by priority (highest first).
        """
        selected = []

        for finfo, priority in scored_index:
            if tracker.remaining <= 0:
                break

            content = self._read_file(finfo.path)
            if content is None:
                continue

            tokens_est = tracker.estimate_tokens(content)

            # If file exceeds remaining budget, try truncating it
            if not tracker.can_fit(content):
                remaining_chars = tracker.remaining * CHARS_PER_TOKEN
                if remaining_chars > 500:
                    content = content[:remaining_chars] + "\n... (truncated to fit budget)"
                    tokens_est = tracker.estimate_tokens(content)
                else:
                    continue

            tracker.consume(content)
            reason = self._selection_reason(finfo, strategy)

            selected.append(ScoredFile(
                info=finfo,
                content=content,
                priority=priority,
                tokens_est=tokens_est,
                reason=reason,
            ))

        return selected

    def _read_file(self, rel_path: str) -> Optional[str]:
        """Read file content from repo. Returns None if unreadable."""
        fpath = os.path.join(self.repo_root, rel_path)
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

    def _selection_reason(self, f: FileInfo, strategy: SamplingStrategy) -> str:
        """Human-readable reason why this file was selected."""
        reasons = []
        if f.is_entry_point:
            reasons.append("entry point")
        if f.last_modified_commit is not None and f.last_modified_commit < 10:
            reasons.append("recently modified")
        if _is_key_directory(f.path):
            reasons.append("key directory")
        if f.import_count > 3:
            reasons.append(f"high dependency ({f.import_count} importers)")
        if not reasons:
            reasons.append(strategy.value)
        return ", ".join(reasons)


# ======================================================================
# Helpers (module-level)
# ======================================================================

def _is_test_file(rel_path: str, basename: str) -> bool:
    """Heuristic: is this file a test file?"""
    if basename.startswith("test_") or basename.endswith("_test.py"):
        return True
    if ".test." in basename or ".spec." in basename:
        return True
    parts = rel_path.replace("\\", "/").split("/")
    return any(p in ("tests", "test", "__tests__", "specs") for p in parts)


def _is_key_directory(path: str) -> bool:
    """Check if a file lives under a key directory."""
    parts = path.replace("\\", "/").split("/")
    if parts:
        return parts[0].lower() in KEY_DIRS
    return False
