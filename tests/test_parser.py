from eden.flp.parser import parse_bytes
from flp_builder import Chan, Clip, Insert, Slot, build_flp, vst_data


def _project(**kw):
    inserts = [
        Insert(name=None, routes=()),  # Master
        Insert(name="Voix Lead", routes=(3,), slots={
            0: Slot("Fruity parametric EQ 2"),
            2: Slot("Fruity Wrapper", data=vst_data("Auto-Tune Pro", "Antares", r"C:\VST3\Auto-Tune Pro.vst3")),
            4: Slot("Fruity Limiter", enabled=False),
        }),
        Insert(name="Instru", volume=10000, pan=-640),
        Insert(name="Bus Voix", routes=(0,), slots={0: Slot("Fruity Reeverb 2")}),
        Insert(name="Coupé", enabled=False),
    ]
    channels = [
        Chan("Lead", insert=1, sample_path=r"C:\Users\K\Documents\Image-Line\FL Studio\Audio\Recorded\Lead.wav"),
        Chan("Beat", insert=2, sample_path=r"C:\Prods\beat.wav"),
        Chan("Sytrus", insert=0, plugin="Sytrus"),
    ]
    clips = [
        Clip(track=1, position=0, length=96 * 4 * 8, channel=0),
        Clip(track=2, position=96 * 4, length=96 * 4 * 16, channel=1),
        Clip(track=3, position=96 * 4 * 2, length=96 * 4, pattern=1),
    ]
    return build_flp(channels, inserts, clips, track_names={1: "Lead", 2: "Instru"}, tempo=150,
                     patterns={1: ("Melodie", [2])}, **kw)


def test_project_header_and_info():
    p = parse_bytes(_project())
    assert p.fl_version == "20.8.4.2576"
    assert p.tempo_bpm == 150
    assert p.ppq == 96
    assert p.time_signature == (4, 4)
    assert p.title == "Test"
    assert p.unknown_event_ids == {}


def test_channels():
    p = parse_bytes(_project())
    lead, beat, synth = p.channels
    assert (lead.name, lead.kind, lead.insert) == ("Lead", "sampler", 1)
    assert lead.sample_path.endswith(r"Recorded\Lead.wav")
    assert (lead.volume_raw, lead.pan_raw) == (10000, 6400)
    assert synth.kind == "instrument" and synth.plugin.internal_name == "Sytrus"


def test_mixer_inserts_slots_routes():
    p = parse_bytes(_project())
    assert len(p.inserts) == 127
    master, voix, instru, bus, coupe = p.inserts[:5]
    assert master.index == 0 and master.label == "Master"
    assert voix.name == "Voix Lead"
    assert [r.target for r in voix.routes] == [3]
    assert [s.index for s in voix.slots] == [0, 2, 4]
    vst = voix.slots[1].plugin
    assert (vst.format, vst.vst_name, vst.vendor) == ("vst3", "Auto-Tune Pro", "Antares")
    assert vst.state_size == 2
    assert voix.slots[2].enabled is False
    assert (instru.volume_raw, instru.pan_raw) == (10000, -640)
    assert coupe.enabled is False
    assert p.inserts[10].is_default


def test_playlist_clips_and_tracks():
    p = parse_bytes(_project())
    arr = p.arrangements[0]
    assert arr.name == "Arrangement"
    assert len(arr.tracks) == 500
    assert arr.tracks[0].name == "Lead" and arr.tracks[0].number == 1
    lead_clip, beat_clip, pat_clip = arr.clips
    assert (lead_clip.track, lead_clip.source, lead_clip.source_index) == (1, "channel", 0)
    assert (pat_clip.source, pat_clip.source_index) == ("pattern", 1)
    # 1 bar at 150 BPM in 4/4 = 1.6 s
    assert abs(beat_clip.start_seconds - 1.6) < 1e-9
    assert p.patterns[0].channels == [2]


def test_old_32_byte_playlist_items():
    old = parse_bytes(_project(legacy_items=True)).arrangements[0].clips
    new = parse_bytes(_project()).arrangements[0].clips
    assert old == new
    assert not parse_bytes(_project(legacy_items=True)).warnings


def test_playlist_length_multiple_of_32_and_60():
    # 15 legacy items = 480 bytes, also a multiple of 60: must still be read as 32-byte items
    clips = [Clip(track=1, position=i * 96, length=96, channel=0) for i in range(15)]
    data = build_flp([Chan("Lead")], [Insert(routes=())], clips, legacy_items=True)
    parsed = parse_bytes(data).arrangements[0].clips
    assert [c.position_ticks for c in parsed] == [i * 96 for i in range(15)]
