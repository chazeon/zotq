"""Click entrypoint for zotq."""

from __future__ import annotations

from dataclasses import dataclass

import click
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from .client import ZotQueryClient
from .config import apply_cli_overrides, load_app_config
from .contracts import build_cli_api_contract
from .errors import BackendConnectionError, ConfigError, IndexNotReadyError, ModeNotSupportedError
from .models import AppConfig, Mode, OutputFormat, QuerySpec, SearchBackend, SearchDefaultsConfig, SearchMode, SearchResult
from .output import render_payload


@dataclass
class RuntimeContext:
    config: AppConfig
    client: ZotQueryClient
    output: OutputFormat
    search_defaults: SearchDefaultsConfig
    verbose: bool


pass_runtime = click.make_pass_decorator(RuntimeContext)


def _attachment_penalty(item_type: str | None, query: QuerySpec) -> float:
    if query.item_type:
        return 1.0
    if (item_type or "").lower() == "attachment":
        return 0.35
    return 1.0


def _build_search_debug_payload(result: SearchResult, query: QuerySpec) -> dict[str, object]:
    hits_payload: list[dict[str, object]] = []
    attachments_in_hits = 0
    normalized_components_present = False

    for rank, hit in enumerate(result.hits, start=1):
        item_type = hit.item.item_type
        if (item_type or "").lower() == "attachment":
            attachments_in_hits += 1

        breakdown = dict(hit.score_breakdown)
        if "lexical_raw" in breakdown or "vector_raw" in breakdown:
            normalized_components_present = True

        hits_payload.append(
            {
                "rank": rank,
                "item_key": hit.item.key,
                "item_type": item_type,
                "score": hit.score,
                "attachment_penalty": _attachment_penalty(item_type, query),
                "score_breakdown": breakdown,
            }
        )

    return {
        "mode": result.executed_mode.value,
        "requested_mode": result.requested_mode.value,
        "hit_count": len(result.hits),
        "attachments_in_hits": attachments_in_hits,
        "normalized_components_present": normalized_components_present,
        "candidate_limits": {
            "backend": query.backend.value,
            "limit": query.limit,
            "offset": query.offset,
            "lexical_k": query.lexical_k,
            "vector_k": query.vector_k,
            "alpha": query.alpha,
            "include_attachments": query.include_attachments,
        },
        "hits": hits_payload,
    }


def _run_with_index_progress(runtime: RuntimeContext, action: str, fn):
    enable_progress = runtime.output == OutputFormat.TABLE
    if not enable_progress:
        return fn(None)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(compact=True),
        transient=True,
    ) as progress:
        collect_task = progress.add_task("Collecting items", total=None)
        index_task = progress.add_task("Indexing items", total=1, completed=0, visible=False)
        enrich_task = progress.add_task("Enriching metadata", total=1, completed=0, visible=False)
        index_started = False
        enrich_started = False

        def callback(phase: str, current: int, total: int | None) -> None:
            nonlocal index_started, enrich_started
            if phase == "collect":
                if total is not None and total > 0:
                    progress.update(collect_task, total=total)
                progress.update(collect_task, completed=max(0, current))
                return

            if phase == "index":
                if not index_started:
                    progress.update(collect_task, description="Collecting items (done)", total=1, completed=1)
                    progress.update(
                        index_task,
                        description=f"{action.capitalize()} index",
                        visible=True,
                        total=max(1, total or 1),
                        completed=max(0, current),
                    )
                    index_started = True
                else:
                    if total is not None:
                        progress.update(index_task, total=max(1, total))
                    progress.update(index_task, completed=max(0, current))
                return

            if phase == "enrich":
                if not enrich_started:
                    if not index_started:
                        progress.update(collect_task, description="Collecting items (done)", total=1, completed=1)
                    progress.update(
                        enrich_task,
                        visible=True,
                        total=max(1, total or 1),
                        completed=max(0, current),
                    )
                    enrich_started = True
                else:
                    if total is not None:
                        progress.update(enrich_task, total=max(1, total))
                    progress.update(enrich_task, completed=max(0, current))
                return

        status = fn(callback)
        if index_started:
            progress.update(index_task, description=f"{action.capitalize()} index (done)")
        if enrich_started:
            progress.update(enrich_task, description="Enriching metadata (done)")
        return status


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("config_path", "-c", "--config", type=click.Path(path_type=str), default=None, help="Path to TOML config file.")
@click.option("profile", "--profile", type=str, default=None, help="Config profile name.")
@click.option("mode", "--mode", type=click.Choice([m.value for m in Mode]), default=None, help="Source mode override.")
@click.option(
    "output",
    "--output",
    type=click.Choice([o.value for o in OutputFormat]),
    default=None,
    help="Output format override.",
)
@click.option("verbose", "--verbose", is_flag=True, default=False, help="Enable verbose output.")
@click.pass_context
def main(ctx: click.Context, config_path: str | None, profile: str | None, mode: str | None, output: str | None, verbose: bool) -> None:
    """zotq CLI."""
    try:
        config = load_app_config(config_path=config_path)
        config = apply_cli_overrides(
            config,
            profile=profile,
            mode=Mode(mode) if mode else None,
            output=OutputFormat(output) if output else None,
        )
        selected_profile = config.require_profile(config.active_profile)
        client = ZotQueryClient(config=config, profile_name=config.active_profile)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    ctx.obj = RuntimeContext(
        config=config,
        client=client,
        output=selected_profile.output,
        search_defaults=selected_profile.search,
        verbose=verbose,
    )
    ctx.call_on_close(client.close)


@main.group("system")
def system_group() -> None:
    """System operations."""


@system_group.command("health")
@pass_runtime
def system_health(runtime: RuntimeContext) -> None:
    try:
        payload = runtime.client.health()
    except BackendConnectionError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(render_payload(payload, runtime.output))


@main.group("search")
def search_group() -> None:
    """Search operations."""


@search_group.command("run")
@click.argument("query", required=False)
@click.option("text", "--text", type=str, default=None)
@click.option("backend", "--backend", type=click.Choice([b.value for b in SearchBackend]), default=None)
@click.option("search_mode", "--search-mode", type=click.Choice([m.value for m in SearchMode]), default=None)
@click.option("allow_fallback", "--allow-fallback/--no-allow-fallback", default=None)
@click.option("title", "--title", type=str, default=None)
@click.option("doi", "--doi", type=str, default=None)
@click.option("journal", "--journal", type=str, default=None)
@click.option("citation_key", "--citation-key", "--citekey", "--bibkey", type=str, default=None)
@click.option("creators", "--creator", type=str, multiple=True)
@click.option("tags", "--tag", type=str, multiple=True)
@click.option("collection", "--collection", type=str, default=None)
@click.option("item_type", "--item-type", type=str, default=None)
@click.option(
    "include_attachments",
    "--attachments/--no-attachments",
    default=True,
    show_default=True,
    help="Include attachment items in search results.",
)
@click.option("year_from", "--year-from", type=int, default=None)
@click.option("year_to", "--year-to", type=int, default=None)
@click.option("alpha", "--alpha", type=float, default=None)
@click.option("lexical_k", "--lexical-k", type=int, default=None)
@click.option("vector_k", "--vector-k", type=int, default=None)
@click.option("style", "--style", type=str, default=None, help="Citation style for bibliography output.")
@click.option("locale", "--locale", type=str, default=None, help="Locale for bibliography output.")
@click.option("linkwrap", "--linkwrap/--no-linkwrap", default=None, help="Wrap bibliography entries with links.")
@click.option("debug", "--debug/--no-debug", default=False, help="Include ranking debug payload.")
@click.option("limit", "--limit", type=int, default=20)
@click.option("offset", "--offset", type=int, default=0)
@pass_runtime
def search_run(
    runtime: RuntimeContext,
    query: str | None,
    text: str | None,
    backend: str | None,
    search_mode: str | None,
    allow_fallback: bool | None,
    title: str | None,
    doi: str | None,
    journal: str | None,
    citation_key: str | None,
    creators: tuple[str, ...],
    tags: tuple[str, ...],
    collection: str | None,
    item_type: str | None,
    include_attachments: bool,
    year_from: int | None,
    year_to: int | None,
    alpha: float | None,
    lexical_k: int | None,
    vector_k: int | None,
    style: str | None,
    locale: str | None,
    linkwrap: bool | None,
    debug: bool,
    limit: int,
    offset: int,
) -> None:
    if query and text and query != text:
        raise click.ClickException("Pass either QUERY or --text, or use the same value.")
    if runtime.output == OutputFormat.BIBTEX and (style or locale or linkwrap is not None):
        raise click.ClickException("--style/--locale/--linkwrap are only supported with --output bib.")

    defaults = runtime.search_defaults

    query_spec = QuerySpec(
        text=text or query,
        backend=SearchBackend(backend) if backend else SearchBackend.AUTO,
        search_mode=SearchMode(search_mode) if search_mode else defaults.default_mode,
        allow_fallback=allow_fallback if allow_fallback is not None else defaults.allow_fallback,
        title=title,
        doi=doi,
        journal=journal,
        citation_key=citation_key,
        creators=list(creators),
        year_from=year_from,
        year_to=year_to,
        tags=list(tags),
        collection=collection,
        item_type=item_type,
        include_attachments=include_attachments,
        alpha=alpha if alpha is not None else defaults.alpha,
        lexical_k=lexical_k if lexical_k is not None else defaults.lexical_k,
        vector_k=vector_k if vector_k is not None else defaults.vector_k,
        debug=debug,
        limit=limit,
        offset=offset,
    )

    try:
        result = runtime.client.search(query_spec)
    except (ModeNotSupportedError, BackendConnectionError, IndexNotReadyError) as exc:
        raise click.ClickException(str(exc)) from exc

    if runtime.output == OutputFormat.BIB:
        keys = [hit.item.key for hit in result.hits]
        entries = runtime.client.get_items_bibliography(keys, style=style, locale=locale, linkwrap=linkwrap)
        click.echo(render_payload("\n\n".join(entries), runtime.output))
        return
    if runtime.output == OutputFormat.BIBTEX:
        keys = [hit.item.key for hit in result.hits]
        entries = runtime.client.get_items_bibtex(keys)
        click.echo(render_payload("\n\n".join(entries), runtime.output))
        return

    payload = result.model_dump(mode="json")
    payload["query"] = query_spec.model_dump(mode="json")
    if debug:
        payload["debug"] = _build_search_debug_payload(result, query_spec)
    click.echo(render_payload(payload, runtime.output))


@main.group("item")
def item_group() -> None:
    """Item operations."""


@item_group.command("get")
@click.argument("key", required=True)
@click.option("style", "--style", type=str, default=None, help="Citation style for bibliography output.")
@click.option("locale", "--locale", type=str, default=None, help="Locale for bibliography output.")
@click.option("linkwrap", "--linkwrap/--no-linkwrap", default=None, help="Wrap bibliography entries with links.")
@pass_runtime
def item_get(runtime: RuntimeContext, key: str, style: str | None, locale: str | None, linkwrap: bool | None) -> None:
    try:
        if runtime.output == OutputFormat.BIB:
            bibliography_payload = runtime.client.get_item_bibliography(key, style=style, locale=locale, linkwrap=linkwrap)
            click.echo(render_payload(bibliography_payload, runtime.output))
            return
        if runtime.output == OutputFormat.BIBTEX:
            if style or locale or linkwrap is not None:
                raise click.ClickException("--style/--locale/--linkwrap are only supported with --output bib.")
            bibtex = runtime.client.get_item_bibtex(key)
            click.echo(render_payload(bibtex or "", runtime.output))
            return
        item = runtime.client.get_item(key)
    except (BackendConnectionError, IndexNotReadyError) as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {"found": item is not None, "item": item.model_dump(mode="json") if item else None}
    click.echo(render_payload(payload, runtime.output))


@item_group.command("citekey")
@click.argument("key", required=True)
@click.option(
    "prefer",
    "--prefer",
    type=click.Choice(["auto", "json", "extra", "bibtex", "rpc"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Citation key source preference.",
)
@pass_runtime
def item_citekey(runtime: RuntimeContext, key: str, prefer: str) -> None:
    try:
        payload = runtime.client.get_item_citation_key(key, prefer=prefer.lower())
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except (BackendConnectionError, IndexNotReadyError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(render_payload(payload, runtime.output))


@main.group("collection")
def collection_group() -> None:
    """Collection operations."""


@collection_group.command("list")
@pass_runtime
def collection_list(runtime: RuntimeContext) -> None:
    try:
        payload = [collection.model_dump(mode="json") for collection in runtime.client.list_collections()]
    except (BackendConnectionError, IndexNotReadyError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(render_payload(payload, runtime.output))


@collection_group.command("export")
@click.argument("key", required=True)
@click.option("export_format", "--format", type=click.Choice(["bibtex"]), default="bibtex", show_default=True)
@click.option("include_children", "--include-children/--no-include-children", default=False, show_default=True)
@click.option("batch_size", "--batch-size", type=click.IntRange(1, 500), default=200, show_default=True)
@pass_runtime
def collection_export(
    runtime: RuntimeContext,
    key: str,
    export_format: str,
    include_children: bool,
    batch_size: int,
) -> None:
    if export_format != "bibtex":
        raise click.ClickException(f"Unsupported collection export format: {export_format}")
    if runtime.output != OutputFormat.BIBTEX:
        raise click.ClickException("collection export requires --output bibtex.")

    try:
        payload = runtime.client.export_collection_bibtex(
            key,
            include_children=include_children,
            batch_size=batch_size,
        )
    except (BackendConnectionError, IndexNotReadyError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(render_payload(payload, runtime.output))


@main.group("tag")
def tag_group() -> None:
    """Tag operations."""


@tag_group.command("list")
@pass_runtime
def tag_list(runtime: RuntimeContext) -> None:
    try:
        payload = [tag.model_dump(mode="json") for tag in runtime.client.list_tags()]
    except BackendConnectionError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(render_payload(payload, runtime.output))


@main.group("index")
def index_group() -> None:
    """Index lifecycle operations."""


@index_group.command("status")
@pass_runtime
def index_status(runtime: RuntimeContext) -> None:
    try:
        payload = runtime.client.index_status().model_dump(mode="json")
    except BackendConnectionError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(render_payload(payload, runtime.output))


@index_group.command("inspect")
@click.option("sample_limit", "--sample-limit", type=int, default=5, show_default=True)
@pass_runtime
def index_inspect(runtime: RuntimeContext, sample_limit: int) -> None:
    try:
        payload = runtime.client.index_inspect(sample_limit=sample_limit)
    except BackendConnectionError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(render_payload(payload, runtime.output))


@index_group.command("sync")
@click.option("full", "--full", is_flag=True, default=False)
@click.option(
    "profiles_only",
    "--profiles-only/--no-profiles-only",
    default=False,
    help="Sync only items with lexical/vector profile-version mismatches.",
)
@click.option("show_progress", "--progress/--no-progress", default=True, help="Show progress in table output.")
@pass_runtime
def index_sync(runtime: RuntimeContext, full: bool, profiles_only: bool, show_progress: bool) -> None:
    if full and profiles_only:
        raise click.ClickException("--profiles-only cannot be combined with --full.")
    try:
        if show_progress:
            status_obj = _run_with_index_progress(
                runtime,
                "sync",
                lambda progress: runtime.client.index_sync(full=full, profiles_only=profiles_only, progress=progress),
            )
        else:
            status_obj = runtime.client.index_sync(full=full, profiles_only=profiles_only)
        status = status_obj.model_dump(mode="json")
    except (BackendConnectionError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {"action": "sync", "full": full, "profiles_only": profiles_only, "status": status}
    click.echo(render_payload(payload, runtime.output))


@index_group.command("rebuild")
@click.option("show_progress", "--progress/--no-progress", default=True, help="Show progress in table output.")
@pass_runtime
def index_rebuild(runtime: RuntimeContext, show_progress: bool) -> None:
    try:
        if show_progress:
            status_obj = _run_with_index_progress(runtime, "rebuild", lambda progress: runtime.client.index_rebuild(progress=progress))
        else:
            status_obj = runtime.client.index_rebuild()
        status = status_obj.model_dump(mode="json")
    except BackendConnectionError as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {"action": "rebuild", "status": status}
    click.echo(render_payload(payload, runtime.output))


@index_group.command("enrich")
@click.option(
    "field",
    "--field",
    type=click.Choice(["citation-key", "doi", "journal", "all"], case_sensitive=False),
    default="citation-key",
    show_default=True,
    help="Field(s) to enrich in-place.",
)
@click.option("show_progress", "--progress/--no-progress", default=True, help="Show progress in table output.")
@pass_runtime
def index_enrich(runtime: RuntimeContext, field: str, show_progress: bool) -> None:
    try:
        if show_progress:
            result = _run_with_index_progress(
                runtime,
                "enrich",
                lambda progress: runtime.client.index_enrich(field=field, progress=progress),
            )
        else:
            result = runtime.client.index_enrich(field=field)
    except (BackendConnectionError, IndexNotReadyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {"action": "enrich", "field": field, "results": result}
    click.echo(render_payload(payload, runtime.output))


@main.command("api-contract")
@pass_runtime
def api_contract(runtime: RuntimeContext) -> None:
    """Emit the CLI API contract model for documentation/testing."""
    payload = build_cli_api_contract().model_dump(mode="json")
    click.echo(render_payload(payload, runtime.output))


if __name__ == "__main__":
    main()
