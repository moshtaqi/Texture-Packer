from __future__ import annotations

import re
from pathlib import Path

from material_texture_studio.models import IMAGE_EXTENSIONS, MaterialSet
from material_texture_studio.presets import MAP_TYPES


def is_image_file(path: Path | str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def normalized_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def tokens_from_name(text: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return [token for token in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if token]


def find_image_files(folder: Path | str, *, recursive: bool = True) -> list[Path]:
    root_folder = Path(folder)
    found: list[Path] = []
    pattern = "**/*" if recursive else "*"
    for path in root_folder.glob(pattern):
        if not path.is_file() or not is_image_file(path):
            continue
        if any(part.startswith(".") for part in path.relative_to(root_folder).parts):
            continue
        if any(part.lower() in {"materialtexturestudio_output", "__pycache__"} for part in path.parts):
            continue
        if is_likely_packed_output(path):
            continue
        found.append(path)
    return sorted(found)


def is_likely_packed_output(path: Path) -> bool:
    tokens = set(tokens_from_name(path.stem))
    compact = normalized_text(path.stem)
    generated_markers = {
        "packed",
        "orm",
        "rma",
        "mrao",
        "arm",
        "maskmap",
    }
    return any(marker in tokens or compact.endswith(marker) for marker in generated_markers)


def score_file_for_map(path: Path, map_type: str) -> int:
    stem = path.stem.lower()
    compact = normalized_text(stem)
    tokens = tokens_from_name(stem)
    info = MAP_TYPES[map_type]
    score = 0

    for keyword in info.keywords:
        key_compact = normalized_text(keyword)
        if len(key_compact) <= 3:
            if key_compact in tokens:
                score += 140
            if tokens and tokens[-1] == key_compact:
                score += 45
        else:
            keyword_tokens = tokens_from_name(keyword)
            if keyword_tokens and tokens[-len(keyword_tokens) :] == keyword_tokens:
                score += 150
            elif key_compact in compact:
                score += 100
            if compact.endswith(key_compact):
                score += 45

    return score


def classify_file(path: Path) -> tuple[str, int] | None:
    scores = [(score_file_for_map(path, key), key) for key in MAP_TYPES]
    score, key = max(scores, key=lambda item: item[0])
    if score <= 0:
        return None
    return key, score


def derive_material_name(path: Path, map_type: str | None = None, *, folder_fallback: bool = False) -> str:
    stem = path.stem
    candidate_types = [map_type] if map_type else list(MAP_TYPES)

    for key in candidate_types:
        if not key:
            continue
        keywords = sorted(MAP_TYPES[key].keywords, key=len, reverse=True)
        for keyword in keywords:
            escaped = re.escape(keyword)
            patterns = [
                rf"([_\-\s\.]+{escaped})$",
                rf"({escaped})$",
            ]
            for pattern in patterns:
                cleaned = re.sub(pattern, "", stem, flags=re.IGNORECASE).strip("_-. ")
                if cleaned != stem:
                    if cleaned:
                        return cleaned
                    if folder_fallback:
                        return path.parent.name.strip("_-. ") or stem

    if folder_fallback:
        return path.parent.name.strip("_-. ") or stem

    return stem.strip("_-. ") or stem


def detect_material_sets(
    folder: Path | str,
    *,
    recursive: bool = True,
    group_by_folder: bool = False,
) -> list[MaterialSet]:
    files = find_image_files(folder, recursive=recursive)
    grouped: dict[str, MaterialSet] = {}
    best_scores: dict[tuple[str, str], int] = {}

    for path in files:
        classified = classify_file(path)
        if not classified:
            continue
        map_type, score = classified
        material_name = derive_material_name(path, map_type, folder_fallback=group_by_folder)
        group_key = f"{path.parent.resolve()}::{material_name}" if group_by_folder else material_name
        material = grouped.setdefault(
            group_key,
            MaterialSet(name=material_name, source_folder=path.parent),
        )
        score_key = (group_key, map_type)

        if score > best_scores.get(score_key, -9999):
            material.maps[map_type] = path
            best_scores[score_key] = score

    return sorted(
        grouped.values(),
        key=lambda item: (str(item.source_folder or "").lower(), item.name.lower()),
    )


def detect_material_sets_by_folder(folder: Path | str) -> list[MaterialSet]:
    return detect_material_sets(folder, recursive=True, group_by_folder=True)


def detect_single_material(folder: Path | str) -> MaterialSet:
    detected = detect_material_sets(folder, recursive=False)
    if not detected:
        return MaterialSet(name=Path(folder).name)
    if len(detected) == 1:
        return detected[0]

    merged = MaterialSet(name=Path(folder).name, source_folder=Path(folder))
    for material in detected:
        for map_type, path in material.maps.items():
            merged.maps.setdefault(map_type, path)
    return merged
