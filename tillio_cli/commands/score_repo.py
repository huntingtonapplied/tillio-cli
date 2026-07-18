"""tillio score — score files, modules, or directories in a repository.

Uses the sampling system (tillio_cli.sampling) for intelligent file selection
instead of linear truncation. Files are ranked by priority (recency, structural
importance, dependency weight) and selected within a token budget that scales
with repo size.
"""

import os
import click
from rich.table import Table
from tillio_cli.git import get_repo_url
from tillio_cli.api import TillioClient, AuthError, APIError
from tillio_cli.output import get_console, is_json, print_json
from tillio_cli.exit_codes import EXIT_AUTH, EXIT_GENERAL, EXIT_VALIDATION
from tillio_cli.sampling import FileSampler, ContentBatcher, ContextBuilder


@click.command("score-repo")
@click.argument("targets", nargs=-1, required=True)
@click.option("--project-id", default=None, help="Tillio project ID (auto-detected from repo URL)")
@click.option("--category", default="TECHNICAL", type=click.Choice(
    ["TECHNICAL", "RESEARCH", "DESIGN", "MARKETING", "BUSINESS", "STEWARDSHIP"],
    case_sensitive=False,
), help="Contribution category")
@click.option("--recursive/--no-recursive", "-r", default=True, help="Recurse into subdirectories (default: yes)")
@click.option("--dry-run", is_flag=True, help="Preview what would be scored")
@click.option("--title", default=None, help="Custom contribution title")
@click.option("--description", default=None, help="Custom description")
@click.pass_context
def score_repo(ctx, targets, project_id, category, recursive, dry_run, title, description):
    """
    Score files, modules, or directories by content.

    Unlike `tillio submit` (which scores commits/diffs), this command scores
    the current state of code — its quality, architecture, and value.

    Files are selected by priority (recency, structural importance, dependency
    weight) and the token budget scales automatically with repo size.

    \b
    Examples:
        tillio score-repo src/services/auth.py         # score a single file
        tillio score-repo src/services/                 # score a directory
        tillio score-repo src/ lib/ --category TECHNICAL
        tillio score-repo src/ --dry-run                # preview only
    """
    json_mode = is_json(ctx)
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False
    console = get_console(ctx) if not json_mode else None

    # Deprecation notice — prefer `tillio eval code`
    if not json_mode:
        click.echo("Note: score-repo is deprecated. Use `tillio eval code` instead.", err=True)

    # Validate targets exist
    all_paths = []
    for target in targets:
        if not os.path.exists(target):
            if not json_mode:
                click.echo(f"✗ Path not found: {target}", err=True)
            continue
        all_paths.append(os.path.relpath(target))

    if not all_paths:
        if json_mode:
            print_json({"error": "No valid paths found", "targets": list(targets)})
        else:
            click.echo("No valid paths found.")
        raise SystemExit(EXIT_GENERAL)

    # --- Sampling: scan, rank, select within token budget ---
    repo_root = os.getcwd()
    sampler = FileSampler(repo_root=repo_root)
    sample_result = sampler.sample(targets=all_paths, recursive=recursive)

    if not sample_result.files:
        if json_mode:
            print_json({"error": "No scoreable files found", "targets": list(targets)})
        else:
            click.echo("No scoreable code files found in the given path(s).")
        raise SystemExit(EXIT_GENERAL)

    total_lines = sample_result.total_lines_scanned
    total_files = sample_result.total_files_scanned
    sampled_count = len(sample_result.files)
    score_type = "file" if sampled_count == 1 and os.path.isfile(targets[0]) else "directory"

    if not json_mode:
        console.print(
            f"Scanned {total_files} file(s), {total_lines:,} lines "
            f"| tier={sample_result.tier.value} strategy={sample_result.strategy.value}"
        )
        console.print(
            f"Selected {sampled_count} files within {sample_result.token_budget:,} token budget "
            f"({sample_result.tokens_used:,} used)"
        )
        click.echo()

    # --- Dry run ---
    if dry_run:
        if json_mode:
            print_json({
                "dry_run": True,
                "score_type": score_type,
                "targets": all_paths,
                "tier": sample_result.tier.value,
                "strategy": sample_result.strategy.value,
                "total_files_scanned": total_files,
                "total_lines": total_lines,
                "files_selected": sampled_count,
                "token_budget": sample_result.token_budget,
                "tokens_used": sample_result.tokens_used,
                "files": [
                    {
                        "path": f.info.path,
                        "lines": f.info.lines,
                        "priority": f.priority,
                        "reason": f.reason,
                    }
                    for f in sample_result.files
                ],
            })
        else:
            table = Table(show_edge=False, pad_edge=False, box=None)
            table.add_column("File", style="cyan")
            table.add_column("Lines", justify="right")
            table.add_column("Priority", justify="right")
            table.add_column("Reason", style="dim")
            for f in sample_result.files[:50]:
                table.add_row(
                    f.info.path,
                    str(f.info.lines),
                    f"{f.priority:.2f}",
                    f.reason,
                )
            console.print(table)
            if sampled_count > 50:
                console.print(f"  ... and {sampled_count - 50} more files", style="dim")
            click.echo()
            console.print("Remove --dry-run to submit for scoring.", style="dim")
        return

    # --- Authenticate ---
    try:
        client = TillioClient()
    except AuthError as e:
        if json_mode:
            print_json({"error": str(e)})
        else:
            click.echo(f"✗ {e}", err=True)
        raise SystemExit(EXIT_AUTH)

    # --- Resolve project ---
    repo_url = None
    try:
        repo_url = get_repo_url()
    except Exception:
        pass

    if not project_id:
        if repo_url:
            project = client.lookup_project(repo_url)
            if project:
                project_id = project["id"]
                if not json_mode:
                    console.print(f"Project: {project['name']}")
            else:
                if not json_mode:
                    console.print(f"Creating project from {repo_url}...")
                try:
                    project = client.post("/v1/projects/from-repo", {"repository_url": repo_url})
                    project_id = project["id"]
                except APIError as e:
                    if json_mode:
                        print_json({"error": f"Failed to create project: {e}"})
                    else:
                        click.echo(f"✗ Failed to create project: {e}", err=True)
                    raise SystemExit(EXIT_GENERAL)
        else:
            if json_mode:
                print_json({"error": "No --project-id and no git remote URL"})
            else:
                click.echo("✗ No --project-id and no git remote URL.", err=True)
            raise SystemExit(EXIT_VALIDATION)

    # --- Batch and score ---
    batcher = ContentBatcher()
    batches = batcher.batch(sample_result.files)
    builder = ContextBuilder()
    repo_name = os.path.basename(repo_root)

    spinner = None
    if not json_mode:
        batch_msg = f"Scoring {sampled_count} files"
        if len(batches) > 1:
            batch_msg += f" in {len(batches)} batches"
        batch_msg += "..."
        click.echo()
        if not ci_mode:
            spinner = console.status(batch_msg, spinner="dots")
            spinner.start()

    # REVISIT: Multi-batch aggregation sends one API call per batch and
    # averages scores weighted by token count. This is a first-pass approach.
    # Alternatives to consider once we have real data:
    #   - Single-pass: concatenate batch summaries into a final scoring call
    #   - Per-file scores: score each file individually, aggregate differently
    #   - Confidence weighting: weight by LLM confidence, not just token count
    all_results = []
    last_error = None

    for batch in batches:
        # Build API payload — same format as before, but with sampled files
        # NOTE: ContextBuilder.build_single() is available for future use when
        # the CLI calls the LLM directly (e.g., offline eval). Currently the
        # backend's _build_path_score_context() handles prompt formatting.
        payload = {
            "paths": all_paths,
            "files": [
                {
                    "path": f.info.path,
                    "content": f.content,
                    "lines": f.info.lines,
                    "size_bytes": f.info.size_bytes,
                }
                for f in batch.files
            ],
            "score_type": score_type,
            "category": category.upper(),
            "title": title,
            "description": description,
            # Include sampling metadata so the backend knows this is priority-sampled
            "sampling_metadata": {
                "tier": sample_result.tier.value,
                "strategy": sample_result.strategy.value,
                "batch_index": batch.batch_index,
                "total_batches": len(batches),
                "files_sampled": sampled_count,
                "files_total": total_files,
                "token_budget": sample_result.token_budget,
            },
        }
        if project_id:
            payload["project_id"] = project_id
        elif repo_url:
            payload["repository_url"] = repo_url

        try:
            result = client.score_paths(payload)
            all_results.append((result, batch.total_tokens))
        except APIError as e:
            last_error = e
            # Continue with remaining batches if possible
            continue

    if spinner:
        spinner.stop()

    if not all_results:
        if json_mode:
            print_json({"error": str(last_error or "All batches failed")})
        else:
            click.echo(f"✗ Scoring failed: {last_error or 'All batches failed'}", err=True)
        raise SystemExit(EXIT_GENERAL)

    # --- Aggregate results across batches ---
    # For single batch, use result directly. For multi-batch, weighted average.
    if len(all_results) == 1:
        final_result = all_results[0][0]
    else:
        final_result = _aggregate_batch_results(all_results)

    # --- Display results ---
    if json_mode:
        # Include sampling info in JSON output
        if isinstance(final_result, dict):
            final_result["sampling"] = {
                "tier": sample_result.tier.value,
                "strategy": sample_result.strategy.value,
                "files_sampled": sampled_count,
                "files_total": total_files,
                "batches": len(batches),
            }
        print_json(final_result)
        return

    evaluation = final_result.get("evaluation") if isinstance(final_result, dict) else None
    if not evaluation:
        data = final_result.get("data", final_result) if isinstance(final_result, dict) else final_result
        evaluation = data.get("evaluation") if isinstance(data, dict) else None

    if evaluation:
        click.echo()
        console.print("[bold]Evaluation Results[/bold]")
        if len(all_results) > 1:
            console.print(f"  (aggregated from {len(all_results)} batches)", style="dim")
        console.print(f"  Confidence: {float(evaluation.get('confidence_score', 0)):.0%}")
        console.print(f"  Novelty:    {float(evaluation.get('novelty_score', 0)):.0%}")
        console.print(f"  Impact:     {float(evaluation.get('impact_score', 0)):.0%}")
        console.print(f"  Alignment:  {float(evaluation.get('alignment_score', 0)):.0%}")
        scope = evaluation.get("scope_score")
        if scope is not None:
            console.print(f"  Scope:      {float(scope):.0%}")
        points = evaluation.get("points_earned")
        if points is not None:
            console.print(f"  Points:     {float(points):.4f}")
        units = evaluation.get("units_assigned")
        if units is not None:
            console.print(f"  Units:      {float(units):.0f}")
        click.echo()
        rationale = evaluation.get("rationale", "")
        if rationale:
            console.print(f"[dim]{rationale}[/dim]")
    else:
        console.print("Contribution submitted — evaluation pending.", style="yellow")

    contribution_id = final_result.get("id") or (
        final_result.get("data", {}).get("id")
        if isinstance(final_result.get("data"), dict) else None
    )
    if contribution_id:
        click.echo()
        console.print(f"Contribution: {contribution_id}", style="dim")


def _aggregate_batch_results(results: list[tuple[dict, int]]) -> dict:
    """Aggregate evaluation results across multiple batches.

    Uses token-weighted averaging for numeric scores.

    REVISIT: Token-weighted averaging assumes that more code = more influence
    on the score. This may not be ideal — a small but critical file might
    deserve more weight. Consider confidence-weighted or quality-weighted
    aggregation once we have enough data to evaluate.
    """
    score_fields = [
        "confidence_score", "novelty_score", "impact_score",
        "alignment_score", "scope_score",
    ]

    total_tokens = sum(tokens for _, tokens in results)
    if total_tokens == 0:
        total_tokens = 1  # avoid division by zero

    # Extract evaluations from each result
    evals = []
    for result, tokens in results:
        ev = None
        if isinstance(result, dict):
            ev = result.get("evaluation")
            if not ev:
                data = result.get("data", result)
                ev = data.get("evaluation") if isinstance(data, dict) else None
        if ev:
            evals.append((ev, tokens))

    if not evals:
        # No evaluations parsed — return the last raw result
        return results[-1][0]

    # Weighted average of scores
    aggregated_eval = {}
    for field in score_fields:
        weighted_sum = sum(
            float(ev.get(field, 0)) * tokens
            for ev, tokens in evals
        )
        aggregated_eval[field] = round(weighted_sum / total_tokens, 4)

    # Concatenate rationales
    rationales = [ev.get("rationale", "") for ev, _ in evals if ev.get("rationale")]
    aggregated_eval["rationale"] = " | ".join(rationales) if rationales else ""

    # Use the first result as the shell, replace evaluation
    shell = results[0][0]
    if isinstance(shell, dict):
        if "evaluation" in shell:
            shell["evaluation"] = aggregated_eval
        elif "data" in shell and isinstance(shell["data"], dict):
            shell["data"]["evaluation"] = aggregated_eval
    return shell
