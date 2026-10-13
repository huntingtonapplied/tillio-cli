"""File sampling system for bulk repo evaluation.

Provides intelligent file selection, token budgeting, batching,
and prompt assembly for LLM-based code evaluation.

Usage:
    from tillio_cli.sampling import FileSampler, ContentBatcher, ContextBuilder

    sampler = FileSampler(repo_root=".")
    result = sampler.sample(targets=["src/"])

    batcher = ContentBatcher()
    batches = batcher.batch(result.files)

    builder = ContextBuilder()
    for batch in batches:
        prompt_content = builder.build_single(result, batch, "my-repo", len(batches))
        # Send prompt_content to LLM evaluation
"""

from tillio_cli.sampling.sampler import FileSampler, FileInfo, ScoredFile, SampleResult
from tillio_cli.sampling.budget import BudgetTracker
from tillio_cli.sampling.batcher import ContentBatcher, Batch
from tillio_cli.sampling.context import ContextBuilder, RepoSummary
from tillio_cli.sampling.constants import (
    RepoSizeTier,
    SamplingStrategy,
    TIER_TOKEN_BUDGETS,
    TIER_STRATEGIES,
)

__all__ = [
    "FileSampler",
    "FileInfo",
    "ScoredFile",
    "SampleResult",
    "BudgetTracker",
    "ContentBatcher",
    "Batch",
    "ContextBuilder",
    "RepoSummary",
    "RepoSizeTier",
    "SamplingStrategy",
    "TIER_TOKEN_BUDGETS",
    "TIER_STRATEGIES",
]
