# Commit policy (tj57 forks)

## Who may appear as author

Every commit on **our** branches (`mcrpc`, fork `main` when it carries our work,
`master` in `mcrpc`) must show:

```text
tj57 <tj57@users.noreply.github.com>
```

No `Co-authored-by: Cursor`, no `mcRPC Workspace`, no other bot/machine identities.

## How to commit

```bash
git -c user.name=tj57 -c user.email=tj57@users.noreply.github.com commit -m "$(cat <<'EOF'
Short imperative summary.

Optional body: why, not what. Mention migration-affecting change when
CONFIG_ENTRY_VERSION / MINOR_VERSION changes.

EOF
)"
```

Never add Cursor trailers. If the editor inserts them, remove before commit.

## Fork history shape (MeshCore / meshcore-ha)

| Branch | Must be |
|--------|---------|
| `main` (MeshCore) | Exact `upstream/main` (real upstream SHAs) |
| `upstream-sync` (meshcore-ha) | Exact `upstream/main` |
| `mcrpc` | `upstream` base + **only our commits** on top |
| `main` (meshcore-ha, HACS default) | Same tip as `mcrpc` (schema-safe install tip) |

GitHub should show roughly **our commit count** ahead of upstream (e.g. ~15 for
meshcore-ha, ~24 for MeshCore `mcrpc`) — **not** hundreds of rewritten upstream
commits.

## NEVER do this

1. **Do not** run `git filter-repo` / `filter-branch` on the **entire** fork
   history to edit messages. That rewrites upstream commits → GitHub shows
   hundreds of “new” commits and breaks compare/PR sync.
2. **Do not** force-push rewritten upstream tags (`companion-v*`, `repeater-v*`,
   etc.).
3. **Do not** use `vmdev`, `cursoragent`, or local `@local` author emails.

## If you must strip a trailer from *our* commits only

```bash
# Example: rewrite ONLY the range after the real upstream tip
git fetch upstream
git checkout mcrpc
git rebase upstream/main \
  --exec 'true'  # or use filter-branch limited to upstream/main..mcrpc
```

Safer for message-only fixes on our tip commits:

```bash
git rebase -i upstream/main   # reword only our commits
```

Or format-patch + am onto a fresh branch from `upstream/main` (preferred recovery).

## Recovery pattern (if history was rewritten again)

```bash
git fetch upstream
# 1) Export only our patches (from last known-good tip)
git format-patch -o /tmp/patches <upstream-base-commit>..<our-tip>
# 2) Reset working branch to REAL upstream
git checkout -B mcrpc upstream/main   # or the exact base we forked from
# 3) Re-apply
git am --3way /tmp/patches/*.patch
# 4) Force-push ONLY mcrpc / our main — never bulk-push all tags
git push --force-with-lease origin mcrpc
```

## Checklist before push

- [ ] `git log upstream/main..HEAD --format='%an <%ae>'` → only `tj57`
- [ ] `git rev-list --count upstream/main..HEAD` → small (our work only)
- [ ] No `Co-authored-by: Cursor` in `git log upstream/main..HEAD`
- [ ] Tags for our releases only (`v2.10.1`, `v1.0.0` on mcrpc) — not upstream firmware tags
