# Estimated severity and repair priority

RoadGuard turns each detection's bounding box into a severity level and each inspection into a repair-priority score. This page states exactly how, so the numbers can be checked and challenged.

## What these numbers are not

A bounding box measures how much of a **photograph** a damage region occupies. How large the damage is on the road depends on camera height, angle, lens and distance, none of which the system knows. So:

- no value here is a length, width, depth or area in real units;
- the same pothole photographed from further away scores lower;
- the result is an **estimated indicator for triage**, not a certified engineering assessment and not a substitute for inspection.

The API, the dashboard and the PDF report carry the same statement.

## Per damage region

All quantities are relative to the image, so the score does not change with image resolution.

```
area_share   = min(1, (box area / image area) / 0.10)
extent_share = min(1, (box long side / longer image side) / 0.50)
score        = 100 x class_weight x (area_weight x area_share + extent_weight x extent_share)
```

| Class | class_weight | area_weight | extent_weight |
| --- | --- | --- | --- |
| Pothole | 1.00 | 0.6 | 0.4 |
| Alligator Crack | 1.00 | 0.6 | 0.4 |
| Longitudinal Crack | 0.75 | 0.3 | 0.7 |
| Transverse Crack | 0.75 | 0.3 | 0.7 |

Why cracks lean on extent: the box around a thin diagonal crack is mostly intact road, so its area overstates the damage. Why cracks are weighted 0.75: a single linear crack is treated as less urgent than a pothole or alligator cracking of the same apparent size. A crack on its own therefore tops out at 75 (High).

These weights and reference values are project assumptions chosen to give a sensible ordering. They are not taken from a pavement-condition standard and have not been calibrated against engineer ratings.

Worked example: a pothole whose box is 20% of the image width and 25% of its height, in a 1280x720 image. `area_share = 0.05 / 0.10 = 0.5`; `extent_share = 0.2 / 0.5 = 0.4`; `score = 100 x 1.0 x (0.6 x 0.5 + 0.4 x 0.4) = 46` (Medium).

## Per inspection

```
score = worst region score
        + 10 x min(1, coverage / 0.30)            coverage = share of the image inside at least one box
        + min(10, 2 x (number of regions - 1))
        capped at 100
```

An image with no detections scores 0.

## Levels

| Score | Level | Suggested action |
| --- | --- | --- |
| 0 to 25 | Low | Monitor |
| above 25 to 50 | Medium | Schedule Repair |
| above 50 to 75 | High | Immediate Repair |
| above 75 | Critical | Urgent Repair |

## Repair priority

```
priority = inspection score x (0.5 + 0.5 x confidence of the worst region)
```

Confidence only ever lowers priority: an uncertain detection of large damage ranks below a confident one, and never above its own severity score.

## Stored values

Each damage row keeps the box (`bbox`), its pixel area, long side and short side, and its severity score and level. Each inspection keeps its level and priority. For model detections `area` is the box area; for DEMO results it is the area of the thresholded blob.

Inspections recorded before this method was introduced keep the values computed at the time, which used a different, resolution-dependent formula with three levels. Old and new scores are not comparable.

## Where it lives

`backend/app/services/severity.py`, with every constant at the top of the file, tested in `backend/tests/test_severity.py`.
