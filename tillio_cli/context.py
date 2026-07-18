"""Context retrieval for AI evaluation — gathers related files for a commit.

Builds a "context bundle" of files related to a commit's changes:
- Import targets: files imported by changed files
- Test files: tests for changed files (by naming convention)
- Sibling files: package-level files (__init__.py, index.ts)
- Callers: files that depend on the changed files (reverse dependency)
"""

import os
import re
import time
from typing import Dict, List, Optional, Set, Tuple

from tillio_cli.git import run_git

# Budget constants (characters)
TOTAL_CONTEXT_BUDGET = 400_000  # ~100K tokens
BUDGET_IMPORT_TARGETS = 0.40
BUDGET_TEST_FILES = 0.25
BUDGET_CALLERS = 0.25
BUDGET_SIBLINGS = 0.10
MAX_SINGLE_FILE = 50_000  # 50KB per file

# Supported extensions for context retrieval
PYTHON_EXTS = {".py"}
JS_EXTS = {".js", ".jsx", ".ts", ".tsx"}
CODE_EXTS = PYTHON_EXTS | JS_EXTS


def build_context_bundle(
    sha: str,
    changed_files: List[str],
    cwd: Optional[str] = None,
) -> Dict:
    """Build a context bundle of related files for a commit.

    Args:
        sha: Commit SHA (used as ref for git show)
        changed_files: List of file paths changed in the commit
        cwd: Repository working directory

    Returns:
        Context bundle dict with import_targets, test_files, sibling_files, callers, stats
    """
    start = time.time()
    seen: Set[str] = set(changed_files)  # don't include changed files themselves

    # Filter to code files only
    code_files = [f for f in changed_files if _ext(f) in CODE_EXTS]

    # 1. Import targets
    import_targets = []
    for f in code_files:
        content = _read_file_at_ref(f, sha, cwd)
        if not content:
            continue
        imports = _extract_imports(content, f, cwd)
        for imp_path in imports:
            if imp_path not in seen and _file_exists_at_ref(imp_path, sha, cwd):
                seen.add(imp_path)
                imp_content = _read_file_at_ref(imp_path, sha, cwd)
                if imp_content:
                    import_targets.append({
                        "path": imp_path,
                        "content": imp_content,
                        "reason": f"imported by {os.path.basename(f)}",
                    })

    # 2. Test files
    test_files = []
    for f in code_files:
        for test_path in _find_test_files(f, cwd):
            if test_path not in seen and _file_exists_at_ref(test_path, sha, cwd):
                seen.add(test_path)
                test_content = _read_file_at_ref(test_path, sha, cwd)
                if test_content:
                    test_files.append({
                        "path": test_path,
                        "content": test_content,
                        "reason": f"test for {os.path.basename(f)}",
                    })

    # 3. Sibling files
    sibling_files = []
    for f in code_files:
        for sib_path in _find_sibling_files(f, cwd):
            if sib_path not in seen and _file_exists_at_ref(sib_path, sha, cwd):
                seen.add(sib_path)
                sib_content = _read_file_at_ref(sib_path, sha, cwd)
                if sib_content:
                    sibling_files.append({
                        "path": sib_path,
                        "content": sib_content,
                        "reason": "package init",
                    })

    # 4. Callers
    callers = []
    for f in code_files:
        for caller_path in _find_callers(f, cwd):
            if caller_path not in seen:
                seen.add(caller_path)
                caller_content = _read_file_at_ref(caller_path, sha, cwd)
                if caller_content:
                    callers.append({
                        "path": caller_path,
                        "content": caller_content,
                        "reason": f"imports {os.path.basename(f)}",
                    })

    # Apply budget limits
    import_targets = _truncate_to_budget(import_targets, int(TOTAL_CONTEXT_BUDGET * BUDGET_IMPORT_TARGETS))
    test_files = _truncate_to_budget(test_files, int(TOTAL_CONTEXT_BUDGET * BUDGET_TEST_FILES))
    callers = _truncate_to_budget(callers, int(TOTAL_CONTEXT_BUDGET * BUDGET_CALLERS))
    sibling_files = _truncate_to_budget(sibling_files, int(TOTAL_CONTEXT_BUDGET * BUDGET_SIBLINGS))

    total_chars = sum(
        len(e.get("content", ""))
        for cat in [import_targets, test_files, sibling_files, callers]
        for e in cat
    )
    total_files = len(import_targets) + len(test_files) + len(sibling_files) + len(callers)
    elapsed_ms = int((time.time() - start) * 1000)

    return {
        "import_targets": import_targets,
        "test_files": test_files,
        "sibling_files": sibling_files,
        "callers": callers,
        "stats": {
            "files_included": total_files,
            "total_chars": total_chars,
            "budget_used_pct": round(total_chars / TOTAL_CONTEXT_BUDGET * 100, 1),
            "retrieval_ms": elapsed_ms,
        },
    }


# ========================================================================
# Import Parsing
# ========================================================================

def _extract_imports(content: str, file_path: str, cwd: Optional[str] = None) -> List[str]:
    """Extract imported file paths from source code."""
    ext = _ext(file_path)
    if ext in PYTHON_EXTS:
        return _extract_imports_python(content, file_path, cwd)
    elif ext in JS_EXTS:
        return _extract_imports_js(content, file_path, cwd)
    return []


def _extract_imports_python(content: str, file_path: str, cwd: Optional[str] = None) -> List[str]:
    """Extract imported module paths from Python source and resolve to file paths."""
    results = []
    root = cwd or "."

    for line in content.splitlines():
        line = line.strip()
        # from package.module import ...
        m = re.match(r'^from\s+(\.{0,3}[\w.]*)\s+import', line)
        if m:
            module = m.group(1)
            resolved = _resolve_python_import(module, file_path, root)
            if resolved:
                results.append(resolved)
            continue
        # import package.module
        m = re.match(r'^import\s+([\w.]+)', line)
        if m:
            module = m.group(1)
            resolved = _resolve_python_import(module, file_path, root)
            if resolved:
                results.append(resolved)

    return results


def _resolve_python_import(module_path: str, source_file: str, cwd: str) -> Optional[str]:
    """Convert a dotted Python import to a repo-relative file path."""
    if not module_path:
        return None

    # Handle relative imports (leading dots)
    if module_path.startswith("."):
        dots = len(module_path) - len(module_path.lstrip("."))
        relative_module = module_path[dots:]
        source_dir = os.path.dirname(source_file)
        # Go up (dots - 1) directories
        for _ in range(dots - 1):
            source_dir = os.path.dirname(source_dir)
        if relative_module:
            candidate = os.path.join(source_dir, relative_module.replace(".", os.sep) + ".py")
        else:
            candidate = os.path.join(source_dir, "__init__.py")
        candidate = os.path.normpath(candidate)
        if os.path.isfile(os.path.join(cwd, candidate)):
            return candidate
        # Try as package
        pkg_init = os.path.join(source_dir, relative_module.replace(".", os.sep), "__init__.py")
        pkg_init = os.path.normpath(pkg_init)
        if os.path.isfile(os.path.join(cwd, pkg_init)):
            return pkg_init
        return None

    # Absolute import — try as file path from repo root
    candidate = module_path.replace(".", os.sep) + ".py"
    if os.path.isfile(os.path.join(cwd, candidate)):
        return candidate
    # Try as package
    pkg_init = module_path.replace(".", os.sep) + os.sep + "__init__.py"
    if os.path.isfile(os.path.join(cwd, pkg_init)):
        return pkg_init

    return None


def _extract_imports_js(content: str, file_path: str, cwd: Optional[str] = None) -> List[str]:
    """Extract imported file paths from JS/TS source."""
    results = []
    root = cwd or "."
    source_dir = os.path.dirname(file_path)

    # Match: import ... from './path' or require('./path')
    patterns = [
        re.compile(r'''(?:import|export)\s+.*?from\s+['"](\.{1,2}/[^'"]+)['"]'''),
        re.compile(r'''require\(\s*['"](\.{1,2}/[^'"]+)['"]\s*\)'''),
    ]

    for line in content.splitlines():
        for pat in patterns:
            m = pat.search(line)
            if m:
                rel_path = m.group(1)
                resolved = _resolve_js_import(rel_path, source_dir, root)
                if resolved:
                    results.append(resolved)

    return results


def _resolve_js_import(rel_path: str, source_dir: str, cwd: str) -> Optional[str]:
    """Resolve a relative JS/TS import to a file path."""
    base = os.path.normpath(os.path.join(source_dir, rel_path))

    # Try exact path, then with extensions, then as directory index
    candidates = [base]
    for ext in [".ts", ".tsx", ".js", ".jsx"]:
        candidates.append(base + ext)
    for idx in ["index.ts", "index.tsx", "index.js", "index.jsx"]:
        candidates.append(os.path.join(base, idx))

    for c in candidates:
        if os.path.isfile(os.path.join(cwd, c)):
            return c

    return None


# ========================================================================
# Related File Discovery
# ========================================================================

def _find_test_files(file_path: str, cwd: Optional[str] = None) -> List[str]:
    """Find test files related to a source file by naming convention."""
    root = cwd or "."
    dirname = os.path.dirname(file_path)
    basename = os.path.basename(file_path)
    name, ext = os.path.splitext(basename)
    results = []

    if ext in PYTHON_EXTS:
        candidates = [
            os.path.join(dirname, f"test_{basename}"),
            os.path.join(dirname, "tests", f"test_{basename}"),
            os.path.join("tests", f"test_{basename}"),
            os.path.join("tests", dirname, f"test_{basename}"),
        ]
    elif ext in JS_EXTS:
        candidates = [
            os.path.join(dirname, f"{name}.test{ext}"),
            os.path.join(dirname, f"{name}.spec{ext}"),
            os.path.join(dirname, "__tests__", f"{name}.test{ext}"),
            os.path.join(dirname, "__tests__", f"{name}.spec{ext}"),
        ]
    else:
        return []

    for c in candidates:
        c = os.path.normpath(c)
        if os.path.isfile(os.path.join(root, c)):
            results.append(c)

    return results


def _find_sibling_files(file_path: str, cwd: Optional[str] = None) -> List[str]:
    """Find package-level files for a file's directory."""
    root = cwd or "."
    dirname = os.path.dirname(file_path)
    ext = _ext(file_path)
    results = []

    if ext in PYTHON_EXTS:
        init = os.path.join(dirname, "__init__.py")
        if os.path.isfile(os.path.join(root, init)):
            results.append(os.path.normpath(init))
    elif ext in JS_EXTS:
        for idx in ["index.ts", "index.tsx", "index.js", "index.jsx"]:
            idx_path = os.path.join(dirname, idx)
            if os.path.isfile(os.path.join(root, idx_path)):
                results.append(os.path.normpath(idx_path))
                break  # only need one index file

    return results


def _find_callers(file_path: str, cwd: Optional[str] = None) -> List[str]:
    """Find files that import the given file using git grep."""
    ext = _ext(file_path)
    basename = os.path.splitext(os.path.basename(file_path))[0]

    if ext in PYTHON_EXTS:
        # Convert file path to module path for grep
        module_path = file_path.replace(os.sep, ".").removesuffix(".py")
        # Also search for the basename (covers relative imports)
        pattern = f"from.*{basename}\\s+import|import.*{basename}"
        glob = "*.py"
    elif ext in JS_EXTS:
        # Search for imports referencing this file's name
        pattern = f"from\\s+['\"].*{basename}['\"]|require\\(['\"].*{basename}['\"]"
        glob = "*.ts *.tsx *.js *.jsx"
    else:
        return []

    try:
        output = run_git(["grep", "-l", "-E", pattern, "--", glob], cwd=cwd)
        callers = [f.strip() for f in output.splitlines() if f.strip()]
        # Don't include the file itself
        callers = [c for c in callers if os.path.normpath(c) != os.path.normpath(file_path)]
        # Limit to 10 callers to avoid overwhelming the context
        return callers[:10]
    except RuntimeError:
        return []


# ========================================================================
# File I/O
# ========================================================================

def _read_file_at_ref(path: str, sha: str, cwd: Optional[str] = None) -> Optional[str]:
    """Read file content at a specific git ref using git show."""
    try:
        content = run_git(["show", f"{sha}:{path}"], cwd=cwd)
        if len(content) > MAX_SINGLE_FILE:
            content = content[:MAX_SINGLE_FILE] + "\n... (file truncated at 50KB)"
        return content
    except RuntimeError:
        return None


def _file_exists_at_ref(path: str, sha: str, cwd: Optional[str] = None) -> bool:
    """Check if a file exists at a specific git ref."""
    try:
        run_git(["cat-file", "-e", f"{sha}:{path}"], cwd=cwd)
        return True
    except RuntimeError:
        return False


# ========================================================================
# Budget / Truncation
# ========================================================================

def _truncate_to_budget(entries: List[Dict], budget_chars: int) -> List[Dict]:
    """Truncate a list of file entries to fit within a character budget."""
    result = []
    used = 0
    for entry in entries:
        content = entry.get("content", "")
        if used + len(content) > budget_chars:
            remaining = budget_chars - used
            if remaining > 1000:  # only include if there's meaningful space left
                entry = dict(entry)
                entry["content"] = content[:remaining] + "\n... (truncated to fit budget)"
                result.append(entry)
            break
        result.append(entry)
        used += len(content)
    return result


# ========================================================================
# Utilities
# ========================================================================

def _ext(path: str) -> str:
    """Get lowercase file extension."""
    return os.path.splitext(path)[1].lower()
