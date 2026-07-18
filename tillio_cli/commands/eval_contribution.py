"""tillio eval contribution <id> — trigger AI evaluation on a contribution."""

import time
import click
from tillio_cli.api import TillioClient, AuthError, APIError
from tillio_cli.output import get_console, is_json, print_json
from tillio_cli.exit_codes import EXIT_AUTH, EXIT_GENERAL, EXIT_SIGINT


MAX_POLL_SECONDS = 120
POLL_INTERVAL = 3


@click.command()
@click.argument("contribution_id")
@click.option("--wait/--no-wait", default=True, show_default=True,
              help="Wait for evaluation to complete")
@click.pass_context
def contribution(ctx, contribution_id: str, wait: bool):
    """Trigger AI evaluation on a contribution by ID."""
    json_mode = is_json(ctx)
    ci_mode = ctx.obj.get("ci", False) if ctx.obj else False

    try:
        client = TillioClient()
    except AuthError as e:
        if json_mode:
            print_json({"error": str(e)})
        else:
            click.echo(f"\u2717 {e}", err=True)
        raise SystemExit(EXIT_AUTH)

    if not wait:
        _eval_async(client, contribution_id, json_mode)
        return

    _eval_streaming(client, contribution_id, json_mode, ci_mode)


def _eval_streaming(client, contribution_id, json_mode, ci_mode=False):
    """Evaluate via SSE streaming endpoint — results in real-time."""
    console = get_console()
    spinner = None
    try:
        for event, event_data in client.evaluate_stream(contribution_id):
            if json_mode:
                print_json({"event": event, **event_data})
                continue

            if event == "evaluating":
                if ci_mode:
                    click.echo(f"Evaluating {contribution_id}...")
                else:
                    spinner = console.status(f"Evaluating {contribution_id}...", spinner="dots")
                    spinner.start()

            elif event == "scored":
                if spinner:
                    spinner.stop()
                units = event_data.get("units", 0)
                confidence = event_data.get("confidence", 0)
                scope = event_data.get("scope")
                rationale = event_data.get("rationale", "")
                score_line = f"\u2713 Score: {units:.0f} units (quality: {confidence:.0%}"
                if scope is not None:
                    score_line += f", scope: {float(scope):.0%}"
                score_line += ")"
                console.print(score_line, style="green")
                if rationale:
                    console.print(f"  {rationale[:120]}", style="dim")

            elif event == "error":
                if spinner:
                    spinner.stop()
                msg = event_data.get("message", "unknown error")
                console.print(f"\u2717 {msg}", style="red")
                raise SystemExit(EXIT_GENERAL)

    except KeyboardInterrupt:
        if spinner:
            spinner.stop()
        click.echo("\nInterrupted. Evaluation may still be running on the server.")
        raise SystemExit(EXIT_SIGINT)

    except APIError as e:
        if spinner:
            spinner.stop()
        if "404" in str(e):
            if not json_mode:
                click.echo("(streaming unavailable \u2014 polling instead)")
            _eval_polling(client, contribution_id, json_mode, ci_mode)
            return

        if json_mode:
            print_json({"error": str(e)})
        else:
            click.echo(f"\u2717 {e}", err=True)
        raise SystemExit(EXIT_GENERAL)


def _eval_async(client, contribution_id, json_mode):
    """Fire-and-forget evaluation request (--no-wait)."""
    try:
        result = client.post(f"/v1/contributions/{contribution_id}/evaluation/request")
    except APIError as e:
        if json_mode:
            print_json({"error": str(e), "contribution_id": contribution_id})
        else:
            click.echo(f"\u2717 {e}", err=True)
        raise SystemExit(EXIT_GENERAL)

    if json_mode:
        print_json(result)
    else:
        click.echo(f"\u26a1 Evaluation queued for {contribution_id}")


def _eval_polling(client, contribution_id, json_mode, ci_mode=False):
    """Poll for evaluation results (legacy fallback)."""
    console = get_console()

    try:
        client.post(f"/v1/contributions/{contribution_id}/evaluation/request")
    except APIError as e:
        if json_mode:
            print_json({"error": str(e), "contribution_id": contribution_id})
        else:
            click.echo(f"\u2717 {e}", err=True)
        raise SystemExit(EXIT_GENERAL)

    if not json_mode:
        click.echo(f"\u26a1 Evaluation requested for {contribution_id}")

    elapsed = 0
    final_result = None
    spinner = None
    if not json_mode and not ci_mode:
        spinner = console.status("Waiting for evaluation...", spinner="dots")
        spinner.start()

    try:
        while elapsed < MAX_POLL_SECONDS:
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

            try:
                contrib = client.get(f"/v1/contributions/{contribution_id}")
                data = contrib.get("data", contrib) if isinstance(contrib, dict) else contrib

                eval_data = data.get("evaluation") if isinstance(data, dict) else None
                status_val = data.get("status", "") if isinstance(data, dict) else ""

                if status_val in ("APPROVED", "REJECTED", "PENDING_REVIEW"):
                    final_result = data
                    break

                if eval_data and eval_data.get("status") in ("COMPLETED", "completed"):
                    final_result = data
                    break

            except APIError:
                pass
    finally:
        if spinner:
            spinner.stop()

    if json_mode:
        print_json(final_result or {"status": "timeout", "contribution_id": contribution_id})
        return

    if final_result:
        eval_info = final_result.get("evaluation", {}) or {}
        units = final_result.get("actual_value") or final_result.get("units_assigned")
        score = eval_info.get("score") or eval_info.get("confidence")
        status_val = final_result.get("status", "")

        if units is not None:
            score_text = f"\u2713 Score: {units} units"
            if score is not None:
                score_text += f" (confidence: {float(score):.0%})"
            console.print(score_text, style="green")
        else:
            console.print(f"\u2713 Evaluation complete \u2014 status: {status_val}", style="green")
    else:
        click.echo(f"\u23f3 Evaluation still in progress. Check later:")
        click.echo(f"  tillio eval contribution {contribution_id}")
