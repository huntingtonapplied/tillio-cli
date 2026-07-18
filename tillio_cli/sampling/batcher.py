"""ContentBatcher — splits scored files into LLM-safe batches.

Each batch fits within a single LLM call's token limit.
Files are never split across batches (but may be truncated within one).
"""

from dataclasses import dataclass

from tillio_cli.sampling.constants import MAX_BATCH_TOKENS, CHARS_PER_TOKEN
from tillio_cli.sampling.sampler import ScoredFile


@dataclass
class Batch:
    """A group of files that fit within a single LLM call."""
    files: list[ScoredFile]
    total_tokens: int
    batch_index: int


class ContentBatcher:
    """Splits a priority-ranked file list into LLM-safe batches.

    Files arrive pre-sorted by priority, so earlier batches contain
    the most important content.

    REVISIT: MAX_BATCH_TOKENS (18K) assumes we need ~2K tokens for the
    prompt template and ~4K for the response. If the prompt template grows
    significantly or we change MAX_TOKENS on the API call, adjust this.
    """

    def __init__(self, max_batch_tokens: int = MAX_BATCH_TOKENS):
        self.max_batch_tokens = max_batch_tokens

    def batch(self, files: list[ScoredFile]) -> list[Batch]:
        """Split files into batches, respecting token limits.

        Rules:
        - Never split a file across batches.
        - If a single file exceeds max_batch_tokens, truncate it and
          give it its own batch.
        - Files arrive pre-sorted by priority (highest first).
        """
        if not files:
            return []

        batches = []
        current_files: list[ScoredFile] = []
        current_tokens = 0

        for f in files:
            # Oversized single file: truncate and isolate in its own batch
            if f.tokens_est > self.max_batch_tokens:
                # Flush current batch first
                if current_files:
                    batches.append(Batch(
                        files=current_files,
                        total_tokens=current_tokens,
                        batch_index=len(batches),
                    ))
                    current_files = []
                    current_tokens = 0

                truncated = self._truncate_file(f)
                batches.append(Batch(
                    files=[truncated],
                    total_tokens=truncated.tokens_est,
                    batch_index=len(batches),
                ))
                continue

            # Would this file overflow the current batch?
            if current_tokens + f.tokens_est > self.max_batch_tokens:
                # Flush current batch
                if current_files:
                    batches.append(Batch(
                        files=current_files,
                        total_tokens=current_tokens,
                        batch_index=len(batches),
                    ))
                current_files = [f]
                current_tokens = f.tokens_est
            else:
                current_files.append(f)
                current_tokens += f.tokens_est

        # Flush final batch
        if current_files:
            batches.append(Batch(
                files=current_files,
                total_tokens=current_tokens,
                batch_index=len(batches),
            ))

        return batches

    def _truncate_file(self, f: ScoredFile) -> ScoredFile:
        """Truncate an oversized file to fit in a single batch."""
        max_chars = self.max_batch_tokens * CHARS_PER_TOKEN
        truncated_content = f.content[:max_chars] + "\n... (truncated to fit batch limit)"
        return ScoredFile(
            info=f.info,
            content=truncated_content,
            priority=f.priority,
            tokens_est=self.max_batch_tokens,
            reason=f.reason,
        )
