"""Example Inkmill plugin: a session word goal.

Copy this folder into your plugins folder (inkmill --paths) to try it. It adds
a "Tools" menu with two commands. The Progress plugin supersedes it; it stays
here as the smallest complete plugin example.

* Set Word Goal... asks for a number of words to write this session.
* Goal Progress (Ctrl+F8) shows how far along you are.

Settings live under ``[plugins.word_goal]`` in settings.toml.
"""

from inkmill.screens.dialogs import InputDialog


def register(api):
    api.add_menu("tools", "&Tools")
    baseline = {}

    def words(app):
        doc = app.active_document
        return doc.word_count() if doc else 0

    @api.command("word_goal.set", "Set Word &Goal...", menu="tools")
    async def set_goal(app):
        current = str(api.settings.get("goal", 500))
        answer = await app.push_screen_wait(InputDialog("Word Goal", "Words to write this session:", current))
        if answer and answer.isdigit():
            api.settings["goal"] = int(answer)
            app.settings.save()
            doc = app.active_document
            if doc is not None:
                baseline[doc.id] = words(app)
            app.status.flash(f"Goal set: {answer} words.")

    @api.command("word_goal.progress", "Goal &Progress", "ctrl+f8", menu="tools")
    def progress(app):
        doc = app.active_document
        if doc is None:
            return
        goal = int(api.settings.get("goal", 500))
        written = words(app) - baseline.setdefault(doc.id, words(app))
        pct = min(100, round(100 * written / goal)) if goal else 100
        bar = "#" * (pct // 5) + "." * (20 - pct // 5)
        app.status.flash(f"[{bar}] {written}/{goal} words ({pct}%)", seconds=6)
