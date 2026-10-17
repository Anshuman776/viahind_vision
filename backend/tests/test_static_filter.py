"""Static-object filter: things that never move (clothes, bags) stop being 'people'; people do not."""

from vision.line_crossing import Detection
from vision.static_filter import StaticObjectFilter

FRAME = (1920, 1080)


def box(cx, cy, w=80, h=200):
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def run(f, track, positions, start=0.0, step=0.5):
    kept = []
    for i, (cx, cy) in enumerate(positions):
        kept.append(bool(f.update([Detection(track, box(cx, cy), 0.8)], start + i * step, FRAME)))
    return kept


def test_object_that_never_moves_is_dropped_after_hold_time():
    f = StaticObjectFilter(hold_seconds=10)
    kept = run(f, 1, [(500 + (i % 2), 400) for i in range(30)])  # 15 s, 1 px jitter
    assert all(kept[:20]) and not any(kept[21:])
    assert f.suppressed == 1


def test_person_who_walks_in_then_sits_still_stays_a_person():
    f = StaticObjectFilter(hold_seconds=10)
    walk = [(300 + 40 * i, 400) for i in range(5)]
    sit = [(460, 400)] * 40
    assert all(run(f, 2, walk + sit))


def test_bigger_box_change_counts_as_movement():
    f = StaticObjectFilter(hold_seconds=2)
    f.update([Detection(3, box(500, 400), 0.8)], 0.0, FRAME)
    f.update([Detection(3, box(500, 400, w=80, h=320), 0.8)], 0.5, FRAME)  # stood up
    assert f.update([Detection(3, box(500, 400, w=80, h=320), 0.8)], 5.0, FRAME)


def test_disabled_filter_and_untracked_detections_pass_through():
    off = StaticObjectFilter(hold_seconds=0)
    assert len(run(off, 1, [(500, 400)] * 40)) == 40 and off.update([Detection(1, box(1, 1), 0.9)], 99, FRAME)
    f = StaticObjectFilter(hold_seconds=1)
    assert f.update([Detection(None, box(500, 400), 0.9)], 50.0, FRAME)


def test_forgotten_track_starts_over():
    f = StaticObjectFilter(hold_seconds=3, forget_seconds=2)
    run(f, 4, [(500, 400)] * 10)  # becomes static at 3 s
    assert not f.update([Detection(4, box(500, 400), 0.8)], 5.0, FRAME)
    f.update([], 10.0, FRAME)  # unseen long enough to be forgotten
    assert f.update([Detection(4, box(500, 400), 0.8)], 10.5, FRAME)
