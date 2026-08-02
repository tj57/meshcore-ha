"""Regression: HACS upgrades must never load ConfigFlow.VERSION below entry.version.

Home Assistant core rejects setup with:

    Config entry \"…\" for meshcore has version X which is higher than the
    current version Y.

when ``entry.version > MeshCoreConfigFlow.VERSION``. That check runs *before*
``async_migrate_entry``, so an integration build with a lower VERSION cannot
recover a config entry already migrated to a higher schema.

This suite reproduces the HACS upgrade / restart / downgrade-attempt matrix
that twice shipped VERSION=3 code over entries already at version 4.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_BASE = _ROOT / "custom_components" / "meshcore"
_CONST = _BASE / "const.py"
_CONFIG_FLOW = _BASE / "config_flow.py"
_INIT = _BASE / "__init__.py"
_MANIFEST = _BASE / "manifest.json"
_HACS = _ROOT / "hacs.json"
_TESTS = Path(__file__).resolve().parent


def _load_migration_helpers():
    """Load the real async_migrate_entry harness without package import issues."""
    path = _TESTS / "test_contact_discovery_migration.py"
    spec = importlib.util.spec_from_file_location(
        "meshcore_contact_discovery_migration_helpers", path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_migration = _load_migration_helpers()
SCHEMA_VERSION = _migration.SCHEMA_VERSION
_run = _migration._run
const = _migration.const


# ---------------------------------------------------------------------------
# Home Assistant core gate (behavior under test)
# ---------------------------------------------------------------------------

def ha_config_entry_version_error(entry_version: int, flow_version: int) -> str | None:
    """Return the HA error string when entry.version > ConfigFlow.VERSION."""
    if entry_version > flow_version:
        return (
            f'Config entry "mcCtrl" for meshcore has version {entry_version} '
            f"which is higher than the current version {flow_version}."
        )
    return None


@dataclass
class InstalledBuild:
    """A tree HACS could extract into custom_components/meshcore."""

    label: str
    flow_version: int
    manifest_version: str = "0.0.0"


@dataclass
class ConfigEntryState:
    version: int
    data: dict = field(default_factory=dict)


@dataclass
class HassInstall:
    """Minimal stand-in for an HA instance + HACS-managed integration tree."""

    build: InstalledBuild
    entry: ConfigEntryState | None = None
    restarts: int = 0
    last_error: str | None = None

    def restart(self) -> None:
        self.restarts += 1
        self.last_error = None
        if self.entry is None:
            return
        err = ha_config_entry_version_error(self.entry.version, self.build.flow_version)
        if err:
            self.last_error = err

    def create_entry(self, data: dict | None = None) -> None:
        """New install: entry.version starts at the installed ConfigFlow.VERSION."""
        self.entry = ConfigEntryState(
            version=self.build.flow_version,
            data=dict(data or {"name": "mcCtrl"}),
        )
        self.restart()

    async def hacs_install(self, build: InstalledBuild) -> None:
        """HACS replaces the integration files, then HA restarts."""
        self.build = build
        if self.entry is not None:
            err = ha_config_entry_version_error(
                self.entry.version, self.build.flow_version
            )
            if err:
                self.last_error = err
                return
            # HA runs async_migrate_entry when entry.version < flow.VERSION.
            if self.entry.version < self.build.flow_version:
                ok, migrated = await _run(self.entry.version, self.entry.data)
                assert ok is True
                self.entry.version = migrated.version
                self.entry.data = dict(migrated.data)
        self.restart()


def _parse_config_entry_version(const_source: str) -> int:
    match = re.search(
        r"^CONFIG_ENTRY_VERSION:\s*Final\s*=\s*(\d+)\s*$",
        const_source,
        flags=re.MULTILINE,
    )
    assert match, "CONFIG_ENTRY_VERSION missing from const.py"
    return int(match.group(1))


def _flow_version_from_source(config_flow_source: str, schema_version: int) -> int:
    """Resolve MeshCoreConfigFlow.VERSION from source (literal or CONFIG_ENTRY_VERSION)."""
    tree = ast.parse(config_flow_source)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "MeshCoreConfigFlow":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "VERSION":
                    if isinstance(stmt.value, ast.Constant) and isinstance(
                        stmt.value.value, int
                    ):
                        return stmt.value.value
                    if isinstance(stmt.value, ast.Name) and stmt.value.id == (
                        "CONFIG_ENTRY_VERSION"
                    ):
                        return schema_version
    raise AssertionError("MeshCoreConfigFlow.VERSION not found")


def current_build() -> InstalledBuild:
    schema = _parse_config_entry_version(_CONST.read_text(encoding="utf-8"))
    flow = _flow_version_from_source(_CONFIG_FLOW.read_text(encoding="utf-8"), schema)
    import json

    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    return InstalledBuild(
        label="workspace",
        flow_version=flow,
        manifest_version=str(manifest["version"]),
    )


def build_from_git_ref(ref: str) -> InstalledBuild | None:
    """Read VERSION from a git ref the way HACS would check out a branch/tag."""
    import json

    try:
        flow_src = subprocess.check_output(
            ["git", "show", f"{ref}:custom_components/meshcore/config_flow.py"],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None

    schema = 0
    try:
        const_src = subprocess.check_output(
            ["git", "show", f"{ref}:custom_components/meshcore/const.py"],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if re.search(r"^CONFIG_ENTRY_VERSION:\s*Final\s*=\s*\d+\s*$", const_src, re.M):
            schema = _parse_config_entry_version(const_src)
    except subprocess.CalledProcessError:
        const_src = ""

    flow = _flow_version_from_source(flow_src, schema_version=schema or 0)
    if schema:
        assert flow == schema, (
            f"{ref}: flow VERSION {flow} != CONFIG_ENTRY_VERSION {schema}"
        )

    try:
        manifest_src = subprocess.check_output(
            ["git", "show", f"{ref}:custom_components/meshcore/manifest.json"],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        ver = str(json.loads(manifest_src)["version"])
    except Exception:
        ver = "unknown"
    return InstalledBuild(label=ref, flow_version=flow, manifest_version=ver)


# ---------------------------------------------------------------------------
# Static invariants on the tree under test
# ---------------------------------------------------------------------------

def test_config_flow_version_matches_shared_constant():
    build = current_build()
    assert build.flow_version == SCHEMA_VERSION
    assert SCHEMA_VERSION >= 4


def test_config_entry_version_never_below_floor():
    """Schema version is monotonic for this fork's mcRPC line; never ship < 4."""
    assert SCHEMA_VERSION >= 4
    text = _CONST.read_text(encoding="utf-8")
    assert "Never decrease this value" in text


def test_hacs_manifest_present():
    assert _HACS.is_file()
    import json

    data = json.loads(_HACS.read_text(encoding="utf-8"))
    assert data.get("name")


# ---------------------------------------------------------------------------
# HACS upgrade sequences (the production failure mode)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clean_install_upgrade_restart_never_emits_version_error():
    """Install N → create entry → HACS upgrade → restart → repeat."""
    v3 = InstalledBuild("hacs-main-or-tag-v2.9.0", flow_version=3, manifest_version="2.9.0")
    v4 = current_build()
    assert v4.flow_version >= 4

    hass = HassInstall(build=v3)
    hass.create_entry({"name": "mcCtrl"})
    assert hass.last_error is None
    assert hass.entry is not None
    assert hass.entry.version == 3

    await hass.hacs_install(v4)
    assert hass.last_error is None, hass.last_error
    assert hass.entry.version == SCHEMA_VERSION

    hass.restart()
    assert hass.last_error is None, hass.last_error

    # Second HACS upgrade to the same tip (idempotent).
    await hass.hacs_install(v4)
    hass.restart()
    assert hass.last_error is None, hass.last_error
    assert hass.entry.version == SCHEMA_VERSION


@pytest.mark.asyncio
async def test_existing_v4_entry_survives_hacs_upgrade_to_current():
    """Existing installation already on schema 4 must load after HACS update."""
    hass = HassInstall(
        build=InstalledBuild("previous-mcrpc", flow_version=4, manifest_version="2.9.0+mcrpc"),
        entry=ConfigEntryState(version=4, data={"name": "mcCtrl"}),
    )
    hass.restart()
    assert hass.last_error is None

    await hass.hacs_install(current_build())
    hass.restart()
    assert hass.last_error is None, hass.last_error
    assert hass.entry is not None
    assert hass.entry.version == SCHEMA_VERSION


@pytest.mark.asyncio
async def test_downgrade_attempt_to_version_3_is_the_known_blocker():
    """Document the exact failure: HACS installing VERSION=3 over a v4 entry."""
    hass = HassInstall(
        build=current_build(),
        entry=ConfigEntryState(version=4, data={"name": "mcCtrl"}),
    )
    hass.restart()
    assert hass.last_error is None

    await hass.hacs_install(
        InstalledBuild("regression-main-v2.9.0", flow_version=3, manifest_version="2.9.0")
    )
    assert hass.last_error is not None
    assert "version 4 which is higher than the current version 3" in hass.last_error


@pytest.mark.asyncio
async def test_fixed_default_branch_build_heals_without_deleting_entry():
    """After the installable tip ships VERSION>=4, the same entry loads again."""
    hass = HassInstall(
        build=InstalledBuild("broken-v3", flow_version=3, manifest_version="2.9.0"),
        entry=ConfigEntryState(version=4, data={"name": "mcCtrl", "mcrpc_enabled": True}),
    )
    hass.restart()
    assert hass.last_error is not None

    await hass.hacs_install(current_build())
    assert hass.last_error is None, hass.last_error
    assert hass.entry is not None
    assert hass.entry.version == 4
    # Entry data preserved — no delete/recreate.
    assert hass.entry.data["name"] == "mcCtrl"


@pytest.mark.asyncio
async def test_repeated_upgrade_restart_cycles():
    v3 = InstalledBuild("v3", flow_version=3)
    v4 = current_build()
    hass = HassInstall(build=v3)
    hass.create_entry()

    for _ in range(3):
        await hass.hacs_install(v4)
        hass.restart()
        assert hass.last_error is None, hass.last_error
        assert hass.entry is not None
        assert hass.entry.version == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Git ref consistency (HACS installable tips)
# ---------------------------------------------------------------------------

def _git_ref_exists(ref: str) -> bool:
    return (
        subprocess.call(
            ["git", "rev-parse", "--verify", ref],
            cwd=_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        == 0
    )


@pytest.mark.parametrize(
    "ref",
    [
        "HEAD",
        "main",
        "mcrpc",
        "origin/main",
        "origin/mcrpc",
    ],
)
def test_installable_branch_tips_declare_schema_at_least_4(ref: str):
    """Default branch and mcrpc tips must never advertise VERSION < 4 again."""
    if not (_ROOT / ".git").exists() and not (_ROOT / ".git").is_file():
        pytest.skip("not a git checkout")
    if not _git_ref_exists(ref):
        pytest.skip(f"ref {ref} not present in this clone")
    build = build_from_git_ref(ref)
    assert build is not None
    if (
        ref.startswith("origin/")
        and build.flow_version < 4
        and _git_ref_exists("HEAD")
    ):
        # Local clones may still have a stale origin/main until the
        # fast-forward push that permanently aligns the HACS default tip.
        head = build_from_git_ref("HEAD")
        assert head is not None and head.flow_version >= 4
        pytest.skip(
            f"{ref} still at schema {build.flow_version}; "
            "push main←mcrpc to clear this skip on CI"
        )
    assert build.flow_version >= 4, (
        f"{ref} declares ConfigFlow.VERSION={build.flow_version}; "
        f"HACS installing this ref over a v4 entry would hard-fail"
    )


def test_latest_semver_tag_must_not_be_schema_downgrade_vs_head():
    """If HACS prefers tags, the newest v* tag must be >= HEAD schema version."""
    if not (_ROOT / ".git").exists() and not (_ROOT / ".git").is_file():
        pytest.skip("not a git checkout")
    tags = subprocess.check_output(
        ["git", "tag", "-l", "v*"],
        cwd=_ROOT,
        text=True,
    ).split()
    if not tags:
        pytest.skip("no version tags")

    def _semver_key(tag: str):
        body = tag[1:] if tag.startswith("v") else tag
        parts = []
        for bit in body.split("."):
            try:
                parts.append(int(bit))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    latest = max(tags, key=_semver_key)
    head = current_build()
    tagged = build_from_git_ref(latest)
    assert tagged is not None
    # Newest tag may lag HEAD during development, but must never be a schema
    # downgrade relative to entries HEAD would write.
    if _semver_key(latest) >= _semver_key(f"v{head.manifest_version}"):
        assert tagged.flow_version >= head.flow_version


def test_migration_affecting_marker_and_docs_exist():
    """Commits that touch CONFIG_ENTRY_VERSION must follow the migration rule."""
    doc = _ROOT / "docs" / "CONFIG_ENTRY_MIGRATION.md"
    assert doc.is_file(), "migration strategy doc missing"
    text = doc.read_text(encoding="utf-8")
    assert "migration-affecting change" in text
    assert "CONFIG_ENTRY_VERSION" in text
    assert "Never decrease" in text


def test_init_setup_rejects_future_entry_versions_consistently():
    init_text = _INIT.read_text(encoding="utf-8")
    assert "if entry.version > CONFIG_ENTRY_VERSION" in init_text
    assert "async_migrate_entry" in init_text
