"""Git Sync: commit, pull and push the repository the current document is in.

There is no vault. The repository is whichever one contains the document,
found when a command runs, so documents from several repositories can be open
at once. Listing a repository under Git > Repository Settings is optional and
only adds conveniences (pull on open, push after commit, a message template).
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from inkmill.screens.dialogs import ConfirmDialog, InputDialog, TextDialog

from . import gitcmd
from .dialogs import CommitDialog, RepoOptions, RepoSettingsDialog

DEFAULT_MESSAGE = "Update {file}"
SEGMENT_TTL = 5.0


def register(api):
    app = api.app
    roots: dict[str, Path | None] = {}
    segments: dict[str, tuple[float, str]] = {}
    pulled_this_session: set[str] = set()
    busy: set[str] = set()

    # -- settings ------------------------------------------------------------

    def key(root: Path) -> str:
        return root.resolve().as_posix()

    def repo_table(root: Path) -> dict | None:
        repos = api.settings.get("repos", {})
        return repos.get(key(root)) if isinstance(repos, dict) else None

    def options(root: Path) -> RepoOptions:
        table = repo_table(root) or {}
        return RepoOptions(
            pull_on_open=bool(table.get("pull_on_open", False)),
            push_after_commit=bool(table.get("push_after_commit", api.settings.get("push_after_commit", False))),
            pull_mode=str(table.get("pull_mode", api.settings.get("pull_mode", "ff-only"))),
            message=str(table.get("message", api.settings.get("message", DEFAULT_MESSAGE))),
        )

    # -- helpers ---------------------------------------------------------------

    def doc_path():
        doc = app.active_document
        return doc.path.resolve() if doc is not None and doc.path is not None else None

    def has_path(_app) -> bool:
        return doc_path() is not None

    async def root_for(path: Path, *, refresh: bool = False) -> Path | None:
        folder = str(path.parent)
        if refresh or folder not in roots:
            roots[folder] = await api.run_in_thread(gitcmd.repo_root, path)
        return roots[folder]

    async def git(func, *args, **kwargs):
        return await api.run_in_thread(func, *args, **kwargs)

    async def show_problem(title: str, result_text: str) -> None:
        kind = gitcmd.kind(result_text)
        body = gitcmd.advice(result_text)
        detail = result_text.strip()
        if detail and kind:
            body += "\n\nGit said:\n" + "\n".join(detail.splitlines()[-8:])
        await app.push_screen_wait(TextDialog(title, body))

    async def ensure_git() -> bool:
        if gitcmd.git_path() is not None:
            return True
        await app.push_screen_wait(TextDialog("Git is not installed", "Git Sync needs the git command.\n\n" + gitcmd.install_hint()))
        return False

    async def current_repo(*, offer_init: bool = True) -> tuple[Path, Path] | None:
        """(document path, repository root) for the active document, or None."""
        if not await ensure_git():
            return None
        path = doc_path()
        if path is None:
            app.status.flash("Save the document first.")
            return None
        root = await root_for(path)
        if root is None:
            if not offer_init:
                app.status.flash("This document is not in a git repository.")
                return None
            answer = await app.push_screen_wait(
                ConfirmDialog("Not in a repository", f"{path.parent} is not inside a git repository.\nCreate one here?")
            )
            if answer != "yes":
                return None
            result = await git(gitcmd.init, path.parent)
            if not result.ok:
                await show_problem("git init failed", result.text)
                return None
            root = await root_for(path, refresh=True)
            app.status.flash(f"Created a repository in {path.parent}.")
            if root is None:
                return None
        return path, root

    def docs_in(root: Path):
        base = root.resolve()
        for doc in app.docs:
            if doc.path is None:
                continue
            try:
                doc.path.resolve().relative_to(base)
            except ValueError:
                continue
            yield doc

    async def save_open_docs(root: Path, reason: str) -> bool:
        dirty = [d for d in docs_in(root) if d.dirty]
        if not dirty:
            return True
        names = ", ".join(d.title for d in dirty[:4]) + ("..." if len(dirty) > 4 else "")
        answer = await app.push_screen_wait(
            ConfirmDialog("Unsaved documents", f"{names} {'has' if len(dirty) == 1 else 'have'} unsaved changes.\nSave before {reason}?",
                          (("yes", "&Save"), ("cancel", "&Cancel")))
        )
        if answer != "yes":
            return False
        return all(app.save_document(d) for d in dirty)

    async def fix_identity(root: Path) -> bool:
        name, email = await git(gitcmd.get_identity, root)
        name = await app.push_screen_wait(InputDialog("Who are you?", "Git records a name with every commit. Your name:", name))
        if not name:
            return False
        email = await app.push_screen_wait(InputDialog("Who are you?", "Your email address:", email))
        if not email:
            return False
        scope = await app.push_screen_wait(
            ConfirmDialog("Save for", "Use this name for every repository, or only this one?",
                          (("all", "&Every repository"), ("this", "&This one"), ("cancel", "&Cancel")))
        )
        if scope not in ("all", "this"):
            return False
        result = await git(gitcmd.set_identity, root, name, email, global_=scope == "all")
        if not result.ok:
            await show_problem("Could not save your name", result.text)
            return False
        return True

    def fill(template: str, path: Path, root: Path) -> str:
        now = datetime.now()
        doc = app.active_document
        title = doc.title if doc else path.name
        try:
            return template.format(file=path.name, title=title, date=now.strftime("%Y-%m-%d"), time=now.strftime("%H:%M"), repo=root.name)
        except (KeyError, IndexError, ValueError):
            return template

    def refresh_segment_soon(root: Path | None) -> None:
        if root is not None:
            segments.pop(key(root), None)
        api.refresh_status()

    # -- operations ------------------------------------------------------------

    async def do_commit(*, push: bool | None = None) -> None:
        found = await current_repo()
        if found is None:
            return
        path, root = found
        doc = app.active_document
        if doc is not None and doc.dirty and not app.save_document(doc):
            return
        st = await git(gitcmd.status, root)
        if st.error:
            await show_problem("git status failed", st.error)
            return
        rel = gitcmd.relative(root, path)
        others = sum(1 for _, p in st.changes if p != rel)
        open_docs = [d.path for d in docs_in(root)]
        if not st.changed(rel) and not others:
            app.status.flash("Nothing to commit: no changes since the last commit.")
            return
        opts = options(root)
        request = await app.push_screen_wait(
            CommitDialog(
                f"{root.name}  ({st.branch or 'no branch'})",
                path.name,
                fill(opts.message, path, root),
                push=opts.push_after_commit if push is None else push,
                others=others,
                open_count=len(open_docs),
            )
        )
        if request is None:
            return
        if request.scope == "document":
            if not st.changed(rel):
                app.status.flash(f"{path.name} has no changes to commit; choose Everything to commit the rest.")
                return
            paths = [path]
        elif request.scope == "open":
            if not await save_open_docs(root, "committing"):
                return
            paths = [p for p in open_docs if st.changed(gitcmd.relative(root, p))]
            if not paths:
                app.status.flash("None of the open documents have changes.")
                return
        else:
            if not await save_open_docs(root, "committing"):
                return
            paths = None
        for attempt in range(2):
            result = await git(gitcmd.commit, root, request.message, paths)
            if result.ok:
                break
            if gitcmd.kind(result.text) == "identity" and attempt == 0:
                if not await fix_identity(root):
                    return
                continue
            if gitcmd.kind(result.text) == "nothing":
                app.status.flash("Nothing to commit.")
                return
            await show_problem("Commit failed", result.text)
            return
        first = result.out.strip().splitlines()[0] if result.out.strip() else "Committed."
        app.status.flash(first)
        refresh_segment_soon(root)
        if request.push:
            await do_push(root)

    async def do_push(root: Path | None = None) -> bool:
        if root is None:
            found = await current_repo(offer_init=False)
            if found is None:
                return False
            root = found[1]
        st = await git(gitcmd.status, root)
        set_upstream = None
        if st.upstream is None:
            remotes = await git(gitcmd.remotes, root)
            if not remotes:
                await app.push_screen_wait(TextDialog(
                    "No remote",
                    f"{root.name} has no remote to push to. Add one from a terminal, for example:\n\n"
                    "  git remote add origin git@github.com:you/your-repo.git",
                ))
                return False
            remote = "origin" if "origin" in remotes else remotes[0]
            answer = await app.push_screen_wait(
                ConfirmDialog("Push new branch", f"Push {st.branch or 'this branch'} to {remote} and track it from now on?")
            )
            if answer != "yes":
                return False
            set_upstream = remote
        elif st.ahead == 0:
            app.status.flash("Nothing to push: the remote already has every commit.")
            return True
        app.status.flash(f"Pushing {root.name}...", seconds=30)
        result = await git(gitcmd.push, root, set_upstream=set_upstream)
        if not result.ok:
            app.status.flash("Push failed.")
            await show_problem("Push failed", result.text)
            return False
        app.status.flash(f"Pushed {root.name}.")
        refresh_segment_soon(root)
        return True

    async def do_pull(root: Path | None = None, *, quiet: bool = False) -> bool:
        if root is None:
            found = await current_repo(offer_init=False)
            if found is None:
                return False
            root = found[1]
        if key(root) in busy:
            return False
        if not quiet and not await save_open_docs(root, "pulling"):
            return False
        if quiet and any(d.dirty for d in docs_in(root)):
            return False
        st = await git(gitcmd.status, root)
        if st.upstream is None:
            if not quiet:
                app.status.flash(f"{st.branch or 'This branch'} does not track a remote branch; push it first.")
            return False
        busy.add(key(root))
        try:
            before = await git(gitcmd.head, root)
            app.status.flash(f"Pulling {root.name}...", seconds=30)
            mode = options(root).pull_mode
            result = await git(gitcmd.pull, root, mode)
            if not result.ok and gitcmd.kind(result.text) == "diverged":
                if quiet:
                    app.notify(f"{root.name}: you and the remote both have new commits. Use Git > Pull to combine them.",
                               title="Git Sync", severity="warning", timeout=10)
                    return False
                answer = await app.push_screen_wait(ConfirmDialog(
                    "Both sides changed",
                    "You and the remote both have new commits.\nReplay your commits on top of the remote's (rebase)?",
                    (("yes", "&Rebase"), ("cancel", "&Cancel")),
                ))
                if answer != "yes":
                    app.status.flash("Pull cancelled.")
                    return False
                mode = "rebase"
                result = await git(gitcmd.pull, root, mode)
            if not result.ok:
                if gitcmd.kind(result.text) == "conflict":
                    await git(gitcmd.abort_rebase if mode == "rebase" else gitcmd.abort_merge, root)
                app.status.flash("Pull failed.")
                if not quiet:
                    await show_problem("Pull failed", result.text)
                else:
                    app.notify(f"{root.name}: pull failed. {gitcmd.advice(result.text)}", title="Git Sync", severity="warning", timeout=10)
                return False
            after = await git(gitcmd.head, root)
            count = await git(gitcmd.count_between, root, before, after)
            reloaded = 0
            for doc in list(docs_in(root)):
                if doc.changed_on_disk() and not doc.dirty:
                    if app.reload_document(doc):
                        reloaded += 1
            if count:
                note = f" {reloaded} open document(s) reloaded." if reloaded else ""
                app.status.flash(f"Pulled {count} commit(s) into {root.name}.{note}")
            else:
                app.status.flash(f"{root.name} is up to date.")
            pulled_this_session.add(key(root))
            refresh_segment_soon(root)
            return True
        finally:
            busy.discard(key(root))

    # -- commands ----------------------------------------------------------------

    api.add_menu("git", "&Git")

    @api.command("git_sync.commit", "&Commit Document...", "ctrl+f12", menu="git", enabled=has_path,
                 description="Commit the current document with a message")
    async def commit(app):
        await do_commit()

    @api.command("git_sync.commit_push", "Commit and P&ush...", menu="git", enabled=has_path,
                 description="Commit, then push to the remote")
    async def commit_push(app):
        await do_commit(push=True)

    @api.command("git_sync.pull", "Pu&ll", menu="git", enabled=has_path, separator=True)
    async def pull(app):
        await do_pull()

    @api.command("git_sync.push", "&Push", menu="git", enabled=has_path)
    async def push(app):
        await do_push()

    @api.command("git_sync.sync", "&Sync (Pull, then Push)", menu="git", enabled=has_path)
    async def sync(app):
        found = await current_repo(offer_init=False)
        if found and await do_pull(found[1]):
            await do_push(found[1])

    @api.command("git_sync.sync_tracked", "Sync &All Tracked Repositories", menu="git")
    async def sync_tracked(app):
        if not await ensure_git():
            return
        repos = [Path(k) for k in (api.settings.get("repos") or {})]
        if not repos:
            app.status.flash("No tracked repositories yet. Git > Repository Settings adds the current one.")
            return
        for root in repos:
            if root.is_dir() and await do_pull(root):
                await do_push(root)

    @api.command("git_sync.status", "S&tatus...", menu="git", enabled=has_path, separator=True)
    async def status(app):
        found = await current_repo(offer_init=False)
        if found is None:
            return
        path, root = found
        st = await git(gitcmd.status, root)
        if st.error:
            await show_problem("git status failed", st.error)
            return
        lines = [f"Repository  {root}", f"Branch      {st.branch or '(none)'}"]
        if st.upstream:
            lines.append(f"Tracks      {st.upstream}  ({st.ahead} to push, {st.behind} to pull as of the last fetch)")
        else:
            lines.append("Tracks      nothing (Push sets it up)")
        opts = repo_table(root)
        lines.append(f"Settings    {'tracked' if opts is not None else 'defaults'} (Git > Repository Settings)")
        lines.append("")
        if st.changes:
            lines.append(f"{len(st.changes)} changed file(s):")
            here = gitcmd.relative(root, path)
            for code, rel in st.changes[:200]:
                marker = "  <- this document" if rel == here else ""
                lines.append(f"  {code:<2} {rel}{marker}")
        else:
            lines.append("No uncommitted changes.")
        await app.push_screen_wait(TextDialog("Git Status", "\n".join(lines)))

    @api.command("git_sync.history", "&History of This Document...", menu="git", enabled=has_path)
    async def history(app):
        found = await current_repo(offer_init=False)
        if found is None:
            return
        path, root = found
        result = await git(gitcmd.log, root, path)
        if not result.ok:
            await show_problem("git log failed", result.text)
            return
        body = result.out.strip() or "No commits include this document yet."
        await app.push_screen_wait(TextDialog(f"History: {path.name}", body))

    @api.command("git_sync.settings", "&Repository Settings...", menu="git", enabled=has_path, separator=True,
                 description="Pull on open, push after commit, pull mode and message template for this repository")
    async def repo_settings(app):
        found = await current_repo()
        if found is None:
            return
        _, root = found
        tracked = repo_table(root) is not None
        result = await app.push_screen_wait(RepoSettingsDialog(str(root), options(root), tracked))
        if result is None:
            return
        repos = api.settings.setdefault("repos", {})
        if result.forget:
            repos.pop(key(root), None)
            app.status.flash(f"Stopped tracking {root.name}.")
        else:
            repos[key(root)] = {
                "pull_on_open": result.pull_on_open,
                "push_after_commit": result.push_after_commit,
                "pull_mode": result.pull_mode,
                "message": result.message,
            }
            app.status.flash(f"Saved settings for {root.name}.")
        api.save_settings()

    # -- events and status line ----------------------------------------------------

    @api.on("document_opened")
    async def opened(app, doc) -> None:
        if doc.path is None or gitcmd.git_path() is None:
            return
        root = await root_for(doc.path.resolve())
        if root is None:
            return
        table = repo_table(root)
        if table and table.get("pull_on_open") and key(root) not in pulled_this_session:
            pulled_this_session.add(key(root))
            await do_pull(root, quiet=True)

    @api.on("document_saved")
    def saved(app, doc) -> None:
        if doc.path is not None:
            roots.pop(str(doc.path.resolve().parent), None)
        segments.clear()

    async def compute_segment(root: Path) -> None:
        st = await git(gitcmd.status, root)
        if st.error:
            text = ""
        else:
            text = f"git {st.branch or '?'}"
            if st.changes:
                text += f" *{len(st.changes)}"
            if st.ahead:
                text += f" ^{st.ahead}"
            if st.behind:
                text += f" v{st.behind}"
        segments[key(root)] = (time.monotonic(), text)
        api.refresh_status()

    async def lookup_and_compute(path: Path) -> None:
        root = await root_for(path)
        if root is not None:
            await compute_segment(root)

    @api.status_segment
    def segment(app):
        if not api.settings.get("status", True) or gitcmd.git_path() is None:
            return None
        path = doc_path()
        if path is None:
            return None
        folder = str(path.parent)
        if folder not in roots:
            roots_pending = f"pending:{folder}"
            if roots_pending not in segments:
                segments[roots_pending] = (time.monotonic(), "")
                app.run_worker(lookup_and_compute(path), group="git-segment", exit_on_error=False)
            return None
        root = roots[folder]
        if root is None:
            return None
        hit = segments.get(key(root))
        if hit is None or time.monotonic() - hit[0] > SEGMENT_TTL:
            segments[key(root)] = (time.monotonic(), hit[1] if hit else "")
            app.run_worker(compute_segment(root), group="git-segment", exit_on_error=False)
        return segments[key(root)][1] or None
