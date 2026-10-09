"""Suite module manifest types (runtime-suite contract)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

SUITE_MODULE_IDS: tuple[str, ...] = ("router", "observe", "prompt", "evaluate")

MODULE_BASE_PATHS: dict[str, str] = {
    "router": "/router",
    "observe": "/observe",
    "prompt": "/artifacts",
    "evaluate": "/evaluate",
}


class SuiteModuleId(StrEnum):
    ROUTER = "router"
    OBSERVE = "observe"
    PROMPT = "prompt"
    EVALUATE = "evaluate"


class ModuleCapability(StrEnum):
    """Operations other services gate on — not returned on the public manifest."""

    READ = "read"
    CONFIGURE = "configure"
    INGEST = "ingest"
    INFER = "infer"


class ModuleAccessOut(BaseModel):
    """Effective capability after licence expiry and per-module grace rules."""

    model_config = ConfigDict(extra="forbid")

    read: bool
    configure: bool
    ingest: bool
    infer: bool


class SuiteModuleOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(description="Signed entitlement — module purchased and declared on.")
    base_path: str
    limits: dict[str, str | int | float | bool | None]
    access: ModuleAccessOut


class ModulesManifestOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: str = Field(description="sha256:… over the canonical effective manifest body.")
    modules: dict[str, SuiteModuleOut]
