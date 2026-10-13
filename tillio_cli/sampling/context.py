"""ContextBuilder — assembles LLM prompts from sampled file batches.

Takes a Batch of scored files plus repo metadata and produces a
prompt string ready to send to the evaluation LLM.
"""

from dataclasses import dataclass

from tillio_cli.sampling.sampler import SampleResult
from tillio_cli.sampling.batcher import Batch
from tillio_cli.sampling.constants import RepoSizeTier, SamplingStrategy


@dataclass
class RepoSummary:
    """Lightweight repo metadata for prompt context."""
    name: str
    total_files: int
    total_lines: int
    languages: dict          # ext -> LOC
    top_directories: list    # top dirs by LOC
    tier: RepoSizeTier
    strategy: SamplingStrategy
    total_batches: int
    files_sampled: int

    @classmethod
    def from_sample_result(cls, result: SampleResult, repo_name: str, total_batches: int) -> "RepoSummary":
        return cls(
            name=repo_name,
            total_files=result.total_files_scanned,
            total_lines=result.total_lines_scanned,
            languages=result.languages,
            top_directories=result.top_directories,
            tier=result.tier,
            strategy=result.strategy,
            total_batches=total_batches,
            files_sampled=len(result.files),
        )


class ContextBuilder:
    """Builds evaluation prompt content for a batch of files.

    The output is the file-content section of the prompt, NOT the full
    evaluation prompt. The caller (score_repo or AIEvaluationService)
    wraps this in its own prompt template with scoring instructions.

    REVISIT: The directory tree and repo header add ~300 tokens of
    overhead per batch. For single-batch evals this is fine. For many
    batches, consider including the header only in batch 0 and a
    shorter reference in subsequent batches.
    """

    def build(self, batch: Batch, summary: RepoSummary) -> str:
        """Assemble prompt content for a single batch.

        Returns:
            Formatted string with repo context + file contents.
        """
        sections = []

        # 1. Repo overview
        sections.append(self._repo_header(summary))

        # 2. Abbreviated directory tree
        sections.append(self._dir_tree(summary))

        # 3. Sampling context
        sections.append(self._sampling_context(batch, summary))

        # 4. File contents
        sections.append(self._file_contents(batch))

        return "\n\n".join(sections)

    def build_single(self, result: SampleResult, batch: Batch, repo_name: str, total_batches: int) -> str:
        """Convenience: build context from a SampleResult + Batch."""
        summary = RepoSummary.from_sample_result(result, repo_name, total_batches)
        return self.build(batch, summary)

    # ==================================================================
    # Sections
    # ==================================================================

    def _repo_header(self, summary: RepoSummary) -> str:
        """Repo overview section."""
        # Top languages by LOC
        lang_sorted = sorted(summary.languages.items(), key=lambda x: x[1], reverse=True)
        lang_str = ", ".join(f"{ext} ({loc:,} lines)" for ext, loc in lang_sorted[:5])

        return (
            f"REPOSITORY OVERVIEW:\n"
            f"- Name: {summary.name}\n"
            f"- Total files: {summary.total_files:,}\n"
            f"- Total lines: {summary.total_lines:,}\n"
            f"- Languages: {lang_str}\n"
            f"- Files sampled: {summary.files_sampled} / {summary.total_files}\n"
            f"- Sampling: {summary.strategy.value} ({summary.tier.value} repo)"
        )

    def _dir_tree(self, summary: RepoSummary) -> str:
        """Abbreviated directory tree from top directories."""
        if not summary.top_directories:
            return ""
        tree_lines = ["DIRECTORY STRUCTURE (top dirs by LOC):"]
        for d in summary.top_directories[:10]:
            tree_lines.append(f"  {d}/")
        return "\n".join(tree_lines)

    def _sampling_context(self, batch: Batch, summary: RepoSummary) -> str:
        """Explain what the LLM is seeing and why."""
        lines = []
        if summary.total_batches > 1:
            lines.append(
                f"BATCH {batch.batch_index + 1} of {summary.total_batches} "
                f"({len(batch.files)} files, ~{batch.total_tokens:,} tokens)"
            )
        else:
            lines.append(f"SELECTED FILES ({len(batch.files)} files, ~{batch.total_tokens:,} tokens)")

        lines.append(
            "Note: Files are selected by priority (recency, structural importance, "
            "dependency weight). This is a representative sample, not the full repo."
        )
        return "\n".join(lines)

    def _file_contents(self, batch: Batch) -> str:
        """Format file contents for the prompt."""
        blocks = []
        for f in batch.files:
            header = (
                f"--- {f.info.path} ({f.info.lines} lines) "
                f"[priority={f.priority:.2f}, {f.reason}]"
            )
            blocks.append(f"{header}\n```\n{f.content}\n```")
        return "\nSOURCE CODE:\n" + "\n\n".join(blocks)
