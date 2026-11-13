from dataclasses import dataclass


@dataclass
class SeverityResult:
    score: float
    level: str
    action: str


ACTIONS = {"Low": "Monitor", "Medium": "Schedule Repair", "High": "Immediate Repair"}


def level_for(score: float) -> str:
    if score <= 30:
        return "Low"
    if score <= 70:
        return "Medium"
    return "High"


def assess(area: float, width: float, length: float, surface_area: float) -> SeverityResult:
    area_score = min(area / max(surface_area, 1) * 1000, 100)
    width_score = min(width / 25 * 100, 100)
    length_score = min(length / 500 * 100, 100)
    score = round(0.45 * area_score + 0.30 * width_score + 0.25 * length_score, 1)
    level = level_for(score)
    return SeverityResult(score, level, ACTIONS[level])


def priority(severity_score: float, confidence: float, damage_count: int) -> float:
    return round(min(100, severity_score * 0.72 + confidence * 20 + min(damage_count, 4) * 2), 1)
