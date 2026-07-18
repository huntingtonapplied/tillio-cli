"""Constants for file sampling system.

Shared definitions for repo size tiers, sampling strategies,
file extensions, skip patterns, and priority weights.
"""

from enum import Enum

# ======================================================================
# Repo Size Tiers
# ======================================================================

class RepoSizeTier(Enum):
    SMALL = "small"      # < 10K lines
    MEDIUM = "medium"    # 10K - 50K lines
    LARGE = "large"      # 50K - 200K lines
    HUGE = "huge"        # > 200K lines


class SamplingStrategy(Enum):
    ALL = "all"
    TOP_DIRS_PLUS_SAMPLE = "top_dirs_plus_sample"
    RECENT_PLUS_SAMPLE = "recent_plus_sample"
    RECENT_ONLY = "recent_only"


# Tier thresholds (total scoreable lines)
TIER_THRESHOLDS = {
    RepoSizeTier.SMALL: 10_000,
    RepoSizeTier.MEDIUM: 50_000,
    RepoSizeTier.LARGE: 200_000,
    # HUGE = anything above LARGE
}

# Token budgets per tier
TIER_TOKEN_BUDGETS = {
    RepoSizeTier.SMALL: 20_000,
    RepoSizeTier.MEDIUM: 40_000,
    RepoSizeTier.LARGE: 60_000,
    RepoSizeTier.HUGE: 80_000,
}

# Strategy per tier
TIER_STRATEGIES = {
    RepoSizeTier.SMALL: SamplingStrategy.ALL,
    RepoSizeTier.MEDIUM: SamplingStrategy.TOP_DIRS_PLUS_SAMPLE,
    RepoSizeTier.LARGE: SamplingStrategy.RECENT_PLUS_SAMPLE,
    RepoSizeTier.HUGE: SamplingStrategy.RECENT_ONLY,
}

# ======================================================================
# File Extensions
# ======================================================================

CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".scala",
    ".sh", ".bash", ".zsh", ".sql", ".html", ".css", ".scss", ".vue",
    ".svelte", ".tf", ".yaml", ".yml", ".toml", ".json",
}

# ======================================================================
# Skip Patterns
# ======================================================================

SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", "dist", "build",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    ".next", ".nuxt", "coverage", ".eggs", "vendor", "third_party",
    ".terraform", ".serverless",
}

# ======================================================================
# Key Directories (heuristic)
# ======================================================================
# REVISIT: This list is a starting heuristic based on common project layouts.
# It may need tuning per-language or per-framework once we see real-world
# scoring data. Consider making this configurable per project in the future.

KEY_DIRS = {
    "src", "lib", "app", "core", "pkg", "internal",
    "server", "api", "services", "models", "components",
    "backend", "frontend", "engine", "modules", "packages",
}

# ======================================================================
# Entry Point Detection
# ======================================================================
# REVISIT: Entry point names are language-specific. This covers Python and
# JS/TS conventions. Other ecosystems (Go main.go, Rust main.rs, Java
# Application.java) should be added as we encounter them in real usage.

ENTRY_POINT_NAMES = {
    "main.py", "app.py", "server.py", "wsgi.py", "asgi.py",
    "manage.py", "cli.py", "__main__.py",
    "index.ts", "index.js", "server.ts", "server.js",
    "app.ts", "app.js", "main.ts", "main.js",
    "main.go", "main.rs",
}

# ======================================================================
# Config File Detection
# ======================================================================

CONFIG_EXTS = {".yaml", ".yml", ".toml", ".json"}
CONFIG_NAMES = {
    "config", "settings", "configuration", ".env",
    "pyproject.toml", "package.json", "tsconfig.json",
    "Cargo.toml", "go.mod", "Makefile", "Dockerfile",
}

# ======================================================================
# Priority Scoring Weights
# ======================================================================
# REVISIT: These weights are initial estimates from the architecture doc.
# They have NOT been validated against real evaluation quality. After running
# bulk evals on a few repos, compare LLM scores from priority-sampled files
# vs random-sampled files and adjust weights accordingly.

WEIGHT_RECENCY = 0.30
WEIGHT_KEY_DIR = 0.20
WEIGHT_IMPORTS = 0.20
WEIGHT_ENTRY_POINT = 0.15
WEIGHT_SIZE = 0.10

PENALTY_TEST = 0.5
PENALTY_CONFIG = 0.3

# ======================================================================
# Limits
# ======================================================================

MAX_FILE_SIZE_BYTES = 100_000   # 100KB per file
MAX_BATCH_TOKENS = 18_000       # Per-batch LLM token limit (leave room for prompt + response)
RECENT_COMMITS_LOOKBACK = 50    # How many commits to scan for recency

# REVISIT: The 4 chars/token heuristic is a rough average for English prose
# and code. Claude's actual tokenizer may vary (3.5-4.5 chars/token depending
# on content). If we see budget overruns in practice, drop to 3.5 or add
# tiktoken as an optional dependency.
CHARS_PER_TOKEN = 4
