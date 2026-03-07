"""Contract models for CLI command surface and stable API behavior."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CommandSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: str
    verb: str
    usage: str
    summary: str
    mutating: bool = False
    phase: Literal["v1", "post-v1"] = "v1"

    @property
    def name(self) -> str:
        return f"{self.resource} {self.verb}"


class CliApiContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grammar: str = "zotq <resource> <verb> [options]"
    global_options: list[str] = Field(default_factory=list)
    commands: list[CommandSpec] = Field(default_factory=list)
    reserved_commands: list[CommandSpec] = Field(default_factory=list)

    def command_names(self) -> set[str]:
        return {spec.name for spec in self.commands}

    def reserved_names(self) -> set[str]:
        return {spec.name for spec in self.reserved_commands}


V1_COMMANDS: list[CommandSpec] = [
    CommandSpec(resource="system", verb="health", usage="zotq system health", summary="Backend/source connectivity check"),
    CommandSpec(resource="search", verb="run", usage="zotq search run [QUERY] [options]", summary="Run keyword/fuzzy/semantic/hybrid search"),
    CommandSpec(resource="item", verb="get", usage="zotq item get KEY", summary="Get one item by key"),
    CommandSpec(resource="item", verb="citekey", usage="zotq item citekey KEY", summary="Resolve citation key for one item"),
    CommandSpec(resource="collection", verb="list", usage="zotq collection list", summary="List collections"),
    CommandSpec(resource="tag", verb="list", usage="zotq tag list", summary="List tags"),
    CommandSpec(resource="index", verb="status", usage="zotq index status", summary="Show index status"),
    CommandSpec(resource="index", verb="inspect", usage="zotq index inspect", summary="Inspect index field coverage"),
    CommandSpec(resource="index", verb="sync", usage="zotq index sync [--full]", summary="Sync index incrementally or full"),
    CommandSpec(resource="index", verb="rebuild", usage="zotq index rebuild", summary="Rebuild index from source"),
    CommandSpec(resource="index", verb="enrich", usage="zotq index enrich", summary="Enrich index metadata in place"),
]


RESERVED_WRITE_COMMANDS: list[CommandSpec] = [
    CommandSpec(resource="item", verb="create", usage="zotq item create", summary="Create item", mutating=True, phase="post-v1"),
    CommandSpec(resource="item", verb="update", usage="zotq item update", summary="Update item", mutating=True, phase="post-v1"),
    CommandSpec(resource="item", verb="move", usage="zotq item move", summary="Move item", mutating=True, phase="post-v1"),
    CommandSpec(resource="item", verb="delete", usage="zotq item delete", summary="Delete item", mutating=True, phase="post-v1"),
    CommandSpec(resource="collection", verb="create", usage="zotq collection create", summary="Create collection", mutating=True, phase="post-v1"),
    CommandSpec(resource="collection", verb="add-item", usage="zotq collection add-item", summary="Add item to collection", mutating=True, phase="post-v1"),
    CommandSpec(resource="collection", verb="remove-item", usage="zotq collection remove-item", summary="Remove item from collection", mutating=True, phase="post-v1"),
    CommandSpec(resource="collection", verb="move-item", usage="zotq collection move-item", summary="Move item between collections", mutating=True, phase="post-v1"),
    CommandSpec(resource="collection", verb="delete", usage="zotq collection delete", summary="Delete collection", mutating=True, phase="post-v1"),
    CommandSpec(resource="tag", verb="add", usage="zotq tag add", summary="Add tag", mutating=True, phase="post-v1"),
    CommandSpec(resource="tag", verb="remove", usage="zotq tag remove", summary="Remove tag", mutating=True, phase="post-v1"),
]


def build_cli_api_contract() -> CliApiContract:
    return CliApiContract(
        global_options=[
            "-c, --config PATH",
            "--profile NAME",
            "--mode [local-api|remote]",
            "--output [table|json|jsonl|bib|bibtex]",
            "--verbose",
        ],
        commands=V1_COMMANDS,
        reserved_commands=RESERVED_WRITE_COMMANDS,
    )
