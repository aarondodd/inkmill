from inkmill.app import InkmillApp
from inkmill.config import Settings, State


def make_app(tmp_path, paths=(), **kwargs):
    return InkmillApp(
        paths,
        settings=Settings(restore_session=False, recovery_interval=0),
        state=State(tmp_path / "state.json"),
        load_plugins=False,
        **kwargs,
    )


async def test_restart_hands_documents_to_the_next_app(tmp_path):
    saved = tmp_path / "saved.md"
    saved.write_text("On disk.\n")
    first = make_app(tmp_path, [saved])
    async with first.run_test() as pilot:
        await pilot.press("end", *" more")
        await pilot.press("ctrl+n")
        await pilot.press(*"scratch")
        first.request_restart("Back again.")
        await pilot.pause()
    handoff = first.restart_handoff
    assert handoff is not None and len(handoff.docs) == 2
    assert handoff.active == 1

    second = make_app(tmp_path, handoff=handoff)
    async with second.run_test() as pilot:
        await pilot.pause()
        docs = second.docs.docs
        assert [d.path for d in docs] == [saved, None]
        assert docs[0].text == "On disk. more\n" and docs[0].dirty
        assert docs[1].text == "scratch"
        assert second.active_document is docs[1]
        # The restart's own safety snapshots are cleaned up.
        assert second.recovery.list() == []


async def test_external_change_reloads_clean_document(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("one\n")
    app = make_app(tmp_path, [path])
    async with app.run_test() as pilot:
        doc = app.active_document
        path.write_text("two\n")
        import os

        os.utime(path, (doc.disk_mtime + 5, doc.disk_mtime + 5))
        await pilot.press("ctrl+n")
        app.activate(doc)
        await pilot.pause()
        assert doc.text == "two\n" and not doc.dirty
        assert app.active_editor.text == "two\n"
