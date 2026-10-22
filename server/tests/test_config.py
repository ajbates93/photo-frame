import pytest

from homehub.config import ConfigError, load_config

BASE = 'shared_secret = "s3"\n'


def write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p


def test_missing_secret_fails(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, '[location]\nname="x"\nlat=1.0\nlon=2.0\n'))


def test_placeholder_secret_fails(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, 'shared_secret = "CHANGE_ME"\n'))


def test_missing_file_fails(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.toml")


def test_minimal_config_disables_optional_sections(tmp_path):
    cfg = load_config(write(tmp_path, BASE))
    assert cfg.shared_secret == "s3"
    assert cfg.keep is None and cfg.drive is None and cfg.tapo is None and cfg.speaker is None
    assert cfg.plugs == [] and cfg.people == [] and cfg.location is None
    assert cfg.screen.dim_at == "22:00" and cfg.screen.wake_minutes == 10


def test_full_config(tmp_path):
    cfg = load_config(write(tmp_path, BASE + """
[location]
name = "City"
lat = 51.5
lon = -0.1
[[people]]
id = "a"
name = "A"
color = "#fff"
ics_url = "https://example.invalid/x.ics"
[[calendars]]
id = "c"
label = "C"
color = "#000"
[[plugs]]
host = "192.0.2.1"
room = "Hall"
[keep]
list_title = "Shopping"
email = "x@example.invalid"
[speaker]
name = "Kitchen"
"""))
    assert cfg.location.lat == 51.5
    assert cfg.people[0].ics_url.endswith("x.ics")
    assert cfg.calendars[0].ics_url is None
    assert cfg.plugs[0].confirm is False and cfg.plugs[0].hidden is False
    assert cfg.keep.list_title == "Shopping"
    assert cfg.speaker.name == "Kitchen"


def test_example_config_is_placeholder_only(tmp_path):
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent / "config.example.toml"
    with pytest.raises(ConfigError):
        load_config(example)


def test_repr_hides_secrets(tmp_path):
    cfg = load_config(write(tmp_path, 'shared_secret = "topsecret"\n'
        '[[people]]\nid="a"\nname="A"\ncolor="#fff"\nics_url="https://example.invalid/PRIVATEICS"\n'
        '[tapo]\nusername="u"\npassword="pw-hidden"\n'
        '[keep]\nlist_title="L"\nemail="me@example.invalid"\n'))
    r = repr(cfg)
    for s in ("topsecret", "PRIVATEICS", "pw-hidden", "me@example.invalid"):
        assert s not in r


def test_calendar_settings(tmp_path):
    assert load_config(write(tmp_path, BASE)).calendar.default_travel_mins == 15
    cfg = load_config(write(tmp_path, BASE + "[calendar]\ndefault_travel_mins = 20\n"))
    assert cfg.calendar.default_travel_mins == 20


def test_data_dir_default_and_override(tmp_path):
    from homehub.config import SERVER_DIR, load_config

    p = tmp_path / "c.toml"
    p.write_text('shared_secret = "s"\n')
    assert load_config(p).data_dir == SERVER_DIR / "secrets"
    p.write_text('shared_secret = "s"\ndata_dir = "var"\n')
    assert load_config(p).data_dir == SERVER_DIR / "var"


R = '[[routines]]\nlabel = "Walk"\ndays = ["mon", "fri"]\nstart = "06:45"\nend = "08:00"\n'


def test_routines_default_empty_and_parse(tmp_path):
    assert load_config(write(tmp_path, BASE)).routines == []
    r = load_config(write(tmp_path, BASE + R)).routines[0]
    assert (r.label, r.days, r.start, r.end) == ("Walk", ["mon", "fri"], "06:45", "08:00")


@pytest.mark.parametrize("bad", [
    R.replace('"mon"', '"monday"'),
    R.replace('["mon", "fri"]', '[]'),
    R.replace('["mon", "fri"]', '"mon"'),
    R.replace('"06:45"', '"6.45"'),
    R.replace('"08:00"', '"25:00"'),
    R.replace('"08:00"', '"06:45"'),
    R.replace('"08:00"', '"06:00"'),
    R.replace('label = "Walk"\n', ''),
    R.replace('label = "Walk"', 'label = ""'),
])
def test_invalid_routines_fail(tmp_path, bad):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, BASE + bad))


def test_intervals_parse(tmp_path):
    cfg = load_config(write(tmp_path, BASE + "[intervals]\nweather = 1800\nplugs = 7.5\n"))
    assert cfg.intervals == {"weather": 1800, "plugs": 7.5}


@pytest.mark.parametrize("bad", [
    "wether = 1800",          # unknown key (typo)
    "weather = 0",
    "weather = -5",
    "weather = 4",            # below the 5 s floor
    'weather = "1800"',
    "weather = true",
    "weather = nan",
    "weather = inf",
])
def test_invalid_intervals_fail(tmp_path, bad):
    with pytest.raises(ConfigError, match="intervals"):
        load_config(write(tmp_path, BASE + "[intervals]\n" + bad + "\n"))


def test_intervals_must_be_a_table(tmp_path):
    with pytest.raises(ConfigError, match="intervals"):
        load_config(write(tmp_path, 'intervals = 5\n' + BASE))
