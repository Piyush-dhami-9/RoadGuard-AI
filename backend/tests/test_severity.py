"""Estimated severity and priority from bounding boxes. Everything is relative to the image."""
import pytest
from app.services.severity import ACTIONS, assess_damage, assess_inspection, coverage, level_for, priority

W, H = 1280, 720


def score(name, box_w, box_h, w=W, h=H) -> float:
    return assess_damage(name, box_w, box_h, w, h).score


def test_score_does_not_depend_on_image_resolution():
    """Regression for the audit finding: the same damage scored Medium at 12 MP and Low at 640 px."""
    for name in ("Pothole", "Longitudinal Crack"):
        small = assess_damage(name, 64, 48, 640, 480)
        large = assess_damage(name, 400, 300, 4000, 3000)
        assert small == large


def test_worked_examples_match_the_documented_formula():
    # Pothole, box 20% x 25% of the image: area 0.05/0.10 = 0.5, extent 0.2/0.5 = 0.4 -> 100 x 1.0 x (0.6x0.5 + 0.4x0.4)
    assert score("Pothole", 256, 180) == 46.0
    # Longitudinal crack, box 5% x 60%: area 0.03/0.10 = 0.3, extent (432/1280)/0.5 = 0.675 -> 100 x 0.75 x (0.3x0.3 + 0.7x0.675)
    assert score("Longitudinal Crack", 64, 432) == 42.2
    assert score("Pothole", 0, 0) == 0.0


def test_larger_boxes_score_higher_and_scores_stay_in_range():
    sizes = [(20, 20), (100, 80), (300, 200), (700, 500), (1280, 720)]
    for name in ("Pothole", "Alligator Crack", "Longitudinal Crack", "Transverse Crack"):
        scores = [score(name, *size) for size in sizes]
        assert scores == sorted(scores) and 0 <= scores[0] and scores[-1] <= 100
    assert score("Pothole", 5000, 5000) == 100.0


def test_class_changes_the_score_for_the_same_box():
    assert score("Pothole", 300, 200) == score("Alligator Crack", 300, 200) > score("Longitudinal Crack", 300, 200) == score("Transverse Crack", 300, 200)
    assert score("Longitudinal Crack", 1280, 720) == 75.0, "a crack alone never reaches Critical"
    assert 0 < score("Something New", 300, 200) < score("Pothole", 300, 200)


def test_thin_long_crack_is_scored_on_extent_not_area():
    spanning = score("Transverse Crack", 1100, 40)   # crosses the frame, yet its box covers under 5% of the image
    compact = score("Transverse Crack", 210, 210)    # about the same box area, no extent
    assert spanning > 50 and spanning > compact * 1.5


@pytest.mark.parametrize("value, level", [(0, "Low"), (25, "Low"), (25.1, "Medium"), (50, "Medium"), (50.1, "High"), (75, "High"), (75.1, "Critical"), (100, "Critical")])
def test_levels(value, level):
    assert level_for(value) == level
    assert set(ACTIONS) == {"Low", "Medium", "High", "Critical"}


def test_result_carries_level_and_action():
    result = assess_damage("Pothole", 900, 600, W, H)
    assert (result.level, result.action) == ("Critical", "Urgent Repair")
    assert assess_damage("Pothole", 30, 30, W, H).level == "Low"


def test_coverage_counts_overlap_once():
    box = lambda x1, y1, x2, y2: {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
    assert coverage([], W, H) == 0.0
    assert coverage([box(0, 0, 640, 720)], W, H) == pytest.approx(0.5, abs=0.01)
    assert coverage([box(0, 0, 640, 720), box(0, 0, 640, 720), box(100, 100, 300, 300)], W, H) == pytest.approx(0.5, abs=0.01)
    assert coverage([box(0, 0, 640, 720), box(640, 0, 1280, 720)], W, H) == pytest.approx(1.0, abs=0.01)
    assert coverage([box(-500, -500, 5000, 5000)], W, H) == 1.0


def test_inspection_with_no_damage_is_low_with_zero_priority():
    result = assess_inspection([], 0.0)
    assert (result.score, result.level) == (0.0, "Low")
    assert priority(result.score, 0.0) == 0.0


def test_inspection_score_is_the_worst_region_plus_count_and_coverage():
    assert assess_inspection([40.0], 0.0).score == 40.0
    assert assess_inspection([40.0, 10.0, 5.0], 0.0).score == 44.0          # two extra regions x 2
    assert assess_inspection([40.0] + [1.0] * 20, 0.0).score == 50.0        # count bonus capped at 10
    assert assess_inspection([40.0], 0.15).score == 45.0                    # half the coverage reference -> +5
    assert assess_inspection([40.0], 0.9).score == 50.0                     # coverage bonus capped at 10
    assert assess_inspection([95.0] * 9, 1.0).score == 100.0
    assert assess_inspection([24.0], 0.0).level == "Low" and assess_inspection([24.0, 1.0, 1.0], 0.0).level == "Medium"


def test_priority_is_discounted_by_uncertainty_and_never_exceeds_the_score():
    assert priority(80.0, 1.0) == 80.0
    assert priority(80.0, 0.5) == 60.0
    assert priority(80.0, 0.0) == 40.0
    assert priority(80.0, 7.0) == 80.0 and priority(80.0, -1.0) == 40.0
    assert all(priority(value, confidence) <= value for value in (0, 30, 100) for confidence in (0, 0.3, 1))
