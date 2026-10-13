"""Token budget tracking for file sampling.

Provides character-to-token estimation and budget accounting
for a single evaluation run. Stateless across runs.
"""

from tillio_cli.sampling.constants import CHARS_PER_TOKEN


class BudgetTracker:
    """Tracks token consumption against a fixed budget.

    Uses a chars-per-token heuristic (no external tokenizer dependency).

    REVISIT: The estimate_tokens() heuristic (len // CHARS_PER_TOKEN) is
    approximate. If budget accuracy becomes critical (e.g., hitting API
    context limits), consider adding tiktoken or Anthropic's count_tokens()
    as an optional precision mode.
    """

    def __init__(self, total_budget_tokens: int):
        self.total = total_budget_tokens
        self.used = 0

    def estimate_tokens(self, content: str) -> int:
        """Estimate token count from content string.

        Uses ~4 chars per token heuristic for Claude models.
        """
        return len(content) // CHARS_PER_TOKEN

    def can_fit(self, content: str) -> bool:
        """Check if content fits within remaining budget."""
        return self.used + self.estimate_tokens(content) <= self.total

    def consume(self, content: str) -> int:
        """Consume budget for content. Returns tokens consumed."""
        tokens = self.estimate_tokens(content)
        self.used += tokens
        return tokens

    def consume_tokens(self, tokens: int) -> None:
        """Consume a specific token count (for pre-estimated content)."""
        self.used += tokens

    @property
    def remaining(self) -> int:
        """Remaining token budget."""
        return max(0, self.total - self.used)

    @property
    def usage_pct(self) -> float:
        """Percentage of budget consumed."""
        if self.total == 0:
            return 100.0
        return round(self.used / self.total * 100, 1)
