#!/usr/bin/env python3
"""Fail if HACS-installable git tips declare a ConfigEntry schema downgrade.

Intended for CI and pre-release checks. Compares ConfigFlow.VERSION on:

* HEAD
* main / origin/main (default branch HACS uses)
* mcrpc / origin/mcrpc
* newest v* tag (HACS version picker)

Exits non-zero when any present tip is below the required floor (default: 4),
or when the newest tag is a schema downgrade versus HEAD while its semver is
greater or equal to HEAD's manifest version.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLOOR = 4


def _show(ref: str, path: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "show", f"{ref}:{path}"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None


def _ref_exists(ref: str) -> bool:
    return (
        subprocess.call(
            ["git", "rev-parse", "--verify", ref],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        == 0
    )


def schema_version(ref: str) -> int | None:
    flow = _show(ref, "custom_components/meshcore/config_flow.py")
    if flow is None:
        return None
    const = _show(ref, "custom_components/meshcore/const.py") or ""
    m = re.search(r"^CONFIG_ENTRY_VERSION:\s*Final\s*=\s*(\d+)\s*$", const, re.M)
    if m:
        return int(m.group(1))
    m = re.search(r"^\s*VERSION\s*=\s*(\d+)\s*$", flow, re.M)
    return int(m.group(1)) if m else None


def manifest_version(ref: str) -> str | None:
    raw = _show(ref, "custom_components/meshcore/manifest.json")
    if not raw:
        return None
    return str(json.loads(raw)["version"])


def semver_key(tag: str) -> tuple:
    body = tag[1:] if tag.startswith("v") else tag
    out = []
    for bit in body.split("."):
        try:
            out.append(int(re.match(r"\d+", bit).group(0)) if re.match(r"\d+", bit) else 0)
        except Exception:
            out.append(0)
    return tuple(out)


def working_tree_schema() -> int | None:
    const = (ROOT / "custom_components/meshcore/const.py").read_text(encoding="utf-8")
    m = re.search(r"^CONFIG_ENTRY_VERSION:\s*Final\s*=\s*(\d+)\s*$", const, re.M)
    if m:
        return int(m.group(1))
    flow = (ROOT / "custom_components/meshcore/config_flow.py").read_text(
        encoding="utf-8"
    )
    m = re.search(r"^\s*VERSION\s*=\s*(\d+)\s*$", flow, re.M)
    return int(m.group(1)) if m else None


def main() -> int:
    errors: list[str] = []
    wt = working_tree_schema()
    print(f"{'OK' if wt and wt >= FLOOR else 'FAIL'} working-tree: schema={wt}")
    if wt is None or wt < FLOOR:
        errors.append(f"working tree schema {wt} < floor {FLOOR}")

    tips = ["HEAD", "main", "origin/main", "mcrpc", "origin/mcrpc"]
    local_main_ok = _ref_exists("main") and (schema_version("main") or 0) >= FLOOR
    for ref in tips:
        if not _ref_exists(ref):
            print(f"SKIP {ref} (missing)")
            continue
        ver = schema_version(ref)
        if ver is None:
            errors.append(f"{ref}: could not resolve ConfigFlow.VERSION")
            continue
        if ver < FLOOR and ref == "origin/main" and local_main_ok:
            print(
                f"WARN {ref}: schema={ver} (stale remote default; "
                "fast-forward origin/main to local main before release)"
            )
            continue
        status = "OK" if ver >= FLOOR else "FAIL"
        print(f"{status} {ref}: schema={ver}")
        if ver < FLOOR:
            errors.append(
                f"{ref} declares schema {ver} < floor {FLOOR}; "
                "HACS installing this tip breaks v4 config entries"
            )

    tags = subprocess.check_output(
        ["git", "tag", "-l", "v*"], cwd=ROOT, text=True
    ).split()
    if tags:
        latest = max(tags, key=semver_key)
        tagged = schema_version(latest)
        head_manifest = manifest_version("HEAD") or "0"
        # Prefer working-tree manifest when ahead of HEAD (pre-commit).
        try:
            wt_manifest = json.loads(
                (ROOT / "custom_components/meshcore/manifest.json").read_text(
                    encoding="utf-8"
                )
            )["version"]
            if semver_key(f"v{wt_manifest}") > semver_key(f"v{head_manifest}"):
                head_manifest = str(wt_manifest)
        except Exception:
            pass
        print(
            f"INFO newest tag {latest}: schema={tagged} "
            f"release_manifest={head_manifest}"
        )
        if tagged is None:
            errors.append(f"newest tag {latest}: could not resolve schema")
        elif semver_key(latest) < semver_key(f"v{head_manifest}"):
            print(
                f"WARN newest tag {latest} is older than manifest {head_manifest}; "
                "create a matching tag before publishing to HACS"
            )
        else:
            head_schema = wt or schema_version("HEAD") or 0
            if tagged < head_schema:
                errors.append(
                    f"newest tag {latest} schema {tagged} < HEAD schema {head_schema}"
                )
            if tagged < FLOOR:
                errors.append(
                    f"newest tag {latest} schema {tagged} < floor {FLOOR}"
                )

    if errors:
        print("\nHACS installable schema check FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("\nHACS installable schema check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
