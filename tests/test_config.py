from inkmill.config import Settings, State


def test_settings_roundtrip_keeps_unknown_keys(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text('theme = "amber"\npage_width = "wide"\nfuture_option = 3\n[keys]\n"file.save" = "f2"\n')
    s = Settings.load(path)
    assert s.theme == "amber"
    assert s.page_width == 80  # wrong type ignored
    assert s.keys == {"file.save": "f2"}
    s.save(path)
    again = Settings.load(path)
    assert again.to_dict()["future_option"] == 3


def test_settings_survive_garbage(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("this is = = not toml")
    assert Settings.load(path).theme == "wordperfect"


def test_state_recent_dedupes_and_caps(tmp_path):
    state = State(tmp_path / "state.json")
    for i in range(20):
        state.add_recent(tmp_path / f"f{i}.md")
    state.add_recent(tmp_path / "f5.md")
    assert len(state.recent) == 15
    assert state.recent[0].endswith("f5.md")
    state.save()
    assert State(tmp_path / "state.json").recent == state.recent
