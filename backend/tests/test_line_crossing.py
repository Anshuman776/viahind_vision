"""Entry/exit direction, hysteresis, duplicates, expiry and uncertain cases (synthetic trajectories)."""

from vision.line_crossing import CrossingParams, Detection, LineConfig, LineCrossingCounter

W, H = 640, 480
# Horizontal line across the middle; entry_side=+1 makes "inside" the lower half (moving down = entry).
LINE = LineConfig(0.1, 0.5, 0.9, 0.5, entry_side=1)
PARAMS = CrossingParams(min_confidence=0.4, cooldown_seconds=3.0, track_timeout_seconds=2.0, min_track_hits=3, min_side_frames=2, band=0.03, anchor="center")


def box_at(cx, cy, w=60, h=120):
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def walk(counter, track_id, ys, x=320, t0=0.0, dt=0.1, conf=0.8):
    """Move one track through the given centre y positions; returns (events, end time)."""
    events = []
    t = t0
    for y in ys:
        events += counter.update([Detection(track_id, box_at(x, y), conf)], t, (W, H))
        t += dt
    return events, t


DOWN = [100, 140, 180, 220, 260, 300, 340, 380]
UP = list(reversed(DOWN))


def test_moving_down_is_entry():
    counter = LineCrossingCounter(LINE, PARAMS)
    events, _ = walk(counter, 1, DOWN)
    assert [e.event_type for e in events] == ["entry"]
    assert events[0].track_id == 1
    assert 0.79 < events[0].confidence < 0.81


def test_moving_up_is_exit():
    counter = LineCrossingCounter(LINE, PARAMS)
    events, _ = walk(counter, 1, UP)
    assert [e.event_type for e in events] == ["exit"]


def test_flipped_direction_swaps_entry_and_exit():
    flipped = LineConfig(0.1, 0.5, 0.9, 0.5, entry_side=-1)
    counter = LineCrossingCounter(flipped, PARAMS)
    events, _ = walk(counter, 1, DOWN)
    assert [e.event_type for e in events] == ["exit"]


def test_detection_without_crossing_creates_no_event():
    counter = LineCrossingCounter(LINE, PARAMS)
    events, _ = walk(counter, 1, [100, 110, 120, 110, 100, 105] * 5)
    assert events == []


def test_track_appearing_inside_creates_no_event():
    counter = LineCrossingCounter(LINE, PARAMS)
    events, _ = walk(counter, 1, [300, 320, 340, 360, 380])
    assert events == []


def test_jitter_inside_band_creates_no_event():
    counter = LineCrossingCounter(LINE, PARAMS)
    band_px = PARAMS.band * min(W, H)  # 14.4 px
    ys = [150, 160, 170] + [240 + (band_px - 2) * (1 if i % 2 else -1) for i in range(20)]
    events, _ = walk(counter, 1, ys)
    assert events == []


def test_repeated_frames_do_not_duplicate_entry():
    counter = LineCrossingCounter(LINE, PARAMS)
    events, t = walk(counter, 1, DOWN)
    more, _ = walk(counter, 1, [380] * 30, t0=t)
    assert len(events) == 1 and more == []


def test_low_confidence_detections_are_ignored():
    counter = LineCrossingCounter(LINE, PARAMS)
    events, _ = walk(counter, 1, DOWN, conf=0.2)
    assert events == []
    assert counter.tracks == {}


def test_untracked_detections_are_never_counted():
    counter = LineCrossingCounter(LINE, PARAMS)
    events = []
    for i, y in enumerate(DOWN):
        events += counter.update([Detection(None, box_at(320, y), 0.9)], i * 0.1, (W, H))
    assert events == []


def test_walking_around_the_end_of_the_line_is_not_counted():
    short = LineConfig(0.1, 0.5, 0.4, 0.5)  # covers x 64..256 only
    counter = LineCrossingCounter(short, PARAMS)
    events, _ = walk(counter, 1, DOWN, x=500)
    assert events == []


def test_two_tracks_on_same_person_produce_one_event():
    counter = LineCrossingCounter(LINE, PARAMS)
    events = []
    for i, y in enumerate(DOWN):
        events += counter.update(
            [Detection(1, box_at(320, y), 0.9), Detection(2, box_at(322, y + 2), 0.8)], i * 0.1, (W, H)
        )
    assert [e.event_type for e in events] == ["entry"]


def test_two_people_crossing_together_are_both_counted():
    counter = LineCrossingCounter(LINE, PARAMS)
    events = []
    for i, y in enumerate(DOWN):
        events += counter.update([Detection(1, box_at(200, y), 0.9), Detection(2, box_at(450, y), 0.9)], i * 0.1, (W, H))
    assert sorted(e.track_id for e in events) == [1, 2]


def test_reversal_within_cooldown_is_uncertain():
    counter = LineCrossingCounter(LINE, PARAMS)
    events, t = walk(counter, 1, DOWN)
    back, _ = walk(counter, 1, UP, t0=t)
    assert [e.event_type for e in events + back] == ["entry", "uncertain"]
    assert back[0].reason == "direction_reversal"


def test_reversal_after_cooldown_is_a_real_exit():
    counter = LineCrossingCounter(LINE, PARAMS)
    events, t = walk(counter, 1, DOWN)
    _, t = walk(counter, 1, [380] * 40, t0=t)  # stays inside for 4 seconds
    back, _ = walk(counter, 1, UP, t0=t)
    assert [e.event_type for e in events + back] == ["entry", "exit"]


def test_track_expires_after_timeout():
    counter = LineCrossingCounter(LINE, PARAMS)
    walk(counter, 1, [100, 120, 140])
    assert 1 in counter.tracks
    counter.update([], 10.0, (W, H))
    assert counter.tracks == {}


def test_track_lost_half_way_across_is_uncertain():
    counter = LineCrossingCounter(LINE, PARAMS)
    events, t = walk(counter, 1, [100, 140, 180, 220, 248])  # last point just past centre, inside band
    assert events == []
    expired = counter.update([], t + 5.0, (W, H))
    assert [(e.event_type, e.reason) for e in expired] == [("uncertain", "lost_while_crossing")]


def test_track_lost_before_line_is_silently_dropped():
    counter = LineCrossingCounter(LINE, PARAMS)
    _, t = walk(counter, 1, [100, 140, 180, 220])
    assert counter.update([], t + 5.0, (W, H)) == []


def test_reset_drops_tracks_and_reports_mid_crossing():
    counter = LineCrossingCounter(LINE, PARAMS)
    walk(counter, 1, [100, 140, 180, 220, 248])
    walk(counter, 2, [100, 120, 140], x=100)
    assert counter.reset() == 1
    assert counter.tracks == {}


def test_changing_the_line_restarts_tracks():
    counter = LineCrossingCounter(LINE, PARAMS)
    walk(counter, 1, [100, 140, 180])
    counter.set_line(LineConfig(0.5, 0.1, 0.5, 0.9))
    assert counter.tracks == {}


def test_no_line_means_no_events():
    counter = LineCrossingCounter(None, PARAMS)
    events, _ = walk(counter, 1, DOWN)
    assert events == []
    assert 1 in counter.tracks  # still tracked for the live overlay
