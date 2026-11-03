"""Progress: daily word counts, a daily goal, streaks, sprints and project pace.

Inkmill counts the words each document gained today and keeps the totals in
its state folder. The status line shows today's count against your goal, or
the time left in a sprint. Tools > Progress (Ctrl+F8) shows the details and
the last 30 days.
"""

from __future__ import annotations

import time

from rich.text import Text

from inkmill import frontmatter
from inkmill.config import state_dir
from inkmill.screens.dialogs import InputDialog, TextDialog

from .log import Sprint, WritingLog, bar_chart, pace


def register(api):
    app = api.app
    log = WritingLog(state_dir() / "progress.json")
    state: dict = {"sprint": None, "timer": None, "saver": None}

    def key_for(doc) -> str:
        return str(doc.path.resolve()) if doc.path is not None else f"untitled:{doc.id}"

    def goal() -> int:
        try:
            return int(api.settings.get("daily_goal", 0))
        except (TypeError, ValueError):
            return 0

    def track(doc) -> None:
        if doc is not None:
            log.see(key_for(doc), doc.word_count())

    # -- events ------------------------------------------------------------

    @api.on("ready")
    def ready(app):
        for doc in app.docs:
            track(doc)
        state["saver"] = app.set_interval(20, log.save)

    @api.on("document_opened")
    def opened(app, doc):
        track(doc)

    @api.on("document_activated")
    def activated(app, doc):
        track(doc)

    @api.on("document_changed")
    def changed(app, doc):
        before = log.words()
        track(doc)
        if goal() and before < goal() <= log.words():
            app.notify(f"Daily goal reached: {log.words():,} words today.", title="Progress", timeout=8)
        api.refresh_status()

    @api.on("document_saved")
    def saved(app, doc):
        track(doc)
        log.save()

    # -- status line ---------------------------------------------------------

    @api.status_segment
    def segment(app):
        if not api.settings.get("status", True):
            return None
        sprint: Sprint | None = state["sprint"]
        if sprint is not None:
            left = max(0, int(sprint.started + sprint.minutes * 60 - time.time()))
            gained = sprint_words(sprint)
            return f"Sprint {left // 60}:{left % 60:02d} {gained:+,}"
        words = log.words()
        if goal():
            return f"Today {words:,}/{goal():,}"
        return f"Today {words:+,}" if words else None

    # -- sprints -------------------------------------------------------------

    def total_now() -> int:
        return sum(d.word_count() for d in app.docs)

    def sprint_words(sprint: Sprint) -> int:
        return total_now() - sprint.start_words

    def tick() -> None:
        sprint: Sprint | None = state["sprint"]
        if sprint is None:
            return
        if time.time() >= sprint.started + sprint.minutes * 60:
            finish(completed=True)
        else:
            api.refresh_status()

    def finish(*, completed: bool) -> None:
        sprint: Sprint | None = state["sprint"]
        if sprint is None:
            return
        if state["timer"] is not None:
            state["timer"].stop()
        state["sprint"] = state["timer"] = None
        gained = sprint_words(sprint)
        minutes = max(1, round((time.time() - sprint.started) / 60)) if not completed else sprint.minutes
        log.add_sprint(minutes, gained)
        log.save()
        app.bell()
        app.notify(
            f"{gained:,} words in {minutes} minute(s), {gained / minutes:.0f} a minute.",
            title="Sprint finished" if completed else "Sprint stopped",
            timeout=12,
        )
        api.refresh_status()

    def no_sprint(_app) -> bool:
        return state["sprint"] is None

    api.add_menu("tools", "&Tools")

    @api.command("progress.show", "&Progress...", "ctrl+f8", menu="tools", separator=True,
                 description="Today's words, your goal, streak, sprints and the last 30 days")
    async def show(app):
        for doc in app.docs:
            track(doc)
        words = log.words()
        lines = Text()
        lines.append("Today", style="bold")
        lines.append(f"  {words:,} words" + (f" of {goal():,}" if goal() else "") + "\n")
        streak = log.streak(goal())
        if streak:
            lines.append("Streak", style="bold")
            lines.append(f" {streak} day(s) " + ("at goal" if goal() else "writing") + "\n")
        sprints = log.day().get("sprints", [])
        if sprints:
            lines.append("Sprints", style="bold")
            lines.append(" " + ", ".join(f"{s['at']} {s['words']:+} in {s['minutes']}m" for s in sprints) + "\n")
        project = project_line()
        if project:
            lines.append("Project", style="bold")
            lines.append(f" {project}\n")
        history = log.history(30)
        total = sum(w for _, w in history)
        days_written = sum(1 for _, w in history if w > 0)
        lines.append("\nLast 30 days", style="bold")
        lines.append(f"  {total:,} words, {days_written} day(s) writing" + (", * met the goal" if goal() else "") + "\n\n")
        lines.append("\n".join(bar_chart(history, goal())))
        await app.push_screen_wait(TextDialog("Progress", lines))

    @api.command("progress.goal", "Set Daily &Goal...", menu="tools")
    async def set_goal(app):
        answer = await app.push_screen_wait(InputDialog("Daily Goal", "Words a day (0 for none):", str(goal())))
        if answer is not None and answer.strip().isdigit():
            api.settings["daily_goal"] = int(answer.strip())
            api.save_settings()
            api.refresh_status()
            app.status.flash(f"Daily goal: {int(answer):,} words." if int(answer) else "Daily goal off.")

    @api.command("progress.sprint", "Start Sp&rint...", menu="tools", enabled=no_sprint,
                 description="A timed writing session; the status line counts down")
    async def start_sprint(app):
        default = str(api.settings.get("sprint_minutes", 25))
        answer = await app.push_screen_wait(InputDialog("Sprint", "Minutes:", default))
        if not answer or not answer.strip().isdigit() or int(answer) <= 0:
            return
        minutes = int(answer)
        api.settings["sprint_minutes"] = minutes
        api.save_settings()
        state["sprint"] = Sprint(time.time(), minutes, total_now(), "")
        state["timer"] = app.set_interval(1, tick)
        app.status.flash(f"Sprint: {minutes} minutes. Go.")
        api.refresh_status()

    @api.command("progress.stop", "Stop Spri&nt", menu="tools", enabled=lambda a: state["sprint"] is not None)
    def stop_sprint(app):
        finish(completed=False)

    # -- project target ------------------------------------------------------

    def project_info():
        doc = app.active_document
        if doc is None or doc.path is None:
            return None
        binder = api.service("binder")
        if binder is not None:
            info = binder.project(doc.path)
            if info is not None:
                return info
        meta = frontmatter.read(doc.text)
        target = meta.get("target")
        if not target:
            return None
        return {"title": doc.title, "words": doc.word_count(), "target": target, "deadline": meta.get("deadline", "")}

    def project_line() -> str | None:
        info = project_info()
        if not info:
            return None
        try:
            target = int(str(info["target"]).replace(",", ""))
        except ValueError:
            return None
        words = int(info["words"])
        line = f"{info['title']}: {words:,} of {target:,} words ({min(100, round(100 * words / target)) if target else 0}%)"
        timing = pace(words, target, str(info.get("deadline") or ""))
        return f"{line}, {timing}" if timing else line

    @api.command("progress.target", "Project T&arget...", menu="tools",
                 enabled=lambda a: a.active_document is not None and a.active_document.path is not None,
                 description="A word target and deadline for this document, or its whole binder")
    async def set_target(app):
        doc = app.active_document
        binder = api.service("binder")
        holder = binder.binder_for(doc.path) if binder is not None else None
        holder = holder or doc.path
        holder_doc = app.docs.find_path(holder)
        text = holder_doc.text if holder_doc else holder.read_text(encoding="utf-8")
        meta = frontmatter.read(text)
        target = await app.push_screen_wait(InputDialog("Project Target", f"Total words for {holder.name}:", str(meta.get("target", ""))))
        if not target or not target.strip().replace(",", "").isdigit():
            return
        deadline = await app.push_screen_wait(InputDialog("Project Target", "Deadline (YYYY-MM-DD, blank for none):", str(meta.get("deadline", ""))))
        if deadline is None:
            return
        changes = {"target": target.strip().replace(",", ""), "deadline": deadline.strip() or None}
        new = frontmatter.update(text, changes)
        if holder_doc is not None:
            was_clean = not holder_doc.dirty
            app.replace_document_text(holder_doc, new)
            if was_clean:
                app.save_document(holder_doc)
        else:
            from inkmill.formats import write_text

            write_text(holder, new)
        app.status.flash(project_line() or "Target saved.")
