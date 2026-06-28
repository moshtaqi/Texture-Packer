from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

from material_texture_studio.models import ChannelSource, MaterialSet, OutputTexture, PackResult, Preset


def safe_name(text: str, fallback: str = "Material") -> str:
    text = text.strip() or fallback
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    return text.strip("._ ") or fallback


def _load_rgba(path: Path, size: tuple[int, int] | None = None) -> Image.Image:
    with Image.open(path) as image:
        if size and image.size != size:
            image = image.resize(size, Image.Resampling.LANCZOS)
        return image.convert("RGBA")


def _load_gray(path: Path, size: tuple[int, int] | None = None) -> Image.Image:
    with Image.open(path) as image:
        if size and image.size != size:
            image = image.resize(size, Image.Resampling.LANCZOS)
        return image.convert("L")


def _target_size(material: MaterialSet, preset: Preset) -> tuple[int, int]:
    priority = ["base_color", "normal", "roughness", "smoothness", "metallic", "ao", "height"]
    for key in priority:
        path = material.maps.get(key)
        if path:
            with Image.open(path) as image:
                return image.size

    for output in preset.outputs:
        for source in output.channels.values():
            path = material.maps.get(source.map_type or "")
            if path:
                with Image.open(path) as image:
                    return image.size

    raise ValueError("No usable input textures were assigned.")


def _constant(value: int, size: tuple[int, int]) -> np.ndarray:
    width, height = size
    return np.full((height, width), max(0, min(255, value)), dtype=np.uint8)


def _extract_from_map(
    path: Path,
    channel: str,
    size: tuple[int, int],
    image_cache: dict[tuple[Path, str], np.ndarray],
) -> np.ndarray:
    cache_key = (path, "gray" if channel == "gray" else "rgba")
    if cache_key not in image_cache:
        if channel == "gray":
            image_cache[cache_key] = np.asarray(_load_gray(path, size), dtype=np.uint8)
        else:
            image_cache[cache_key] = np.asarray(_load_rgba(path, size), dtype=np.uint8)

    arr = image_cache[cache_key]
    if channel == "gray":
        return arr

    channel_index = {"r": 0, "g": 1, "b": 2, "a": 3}[channel]
    return arr[:, :, channel_index]


def resolve_channel(
    source: ChannelSource,
    material: MaterialSet,
    size: tuple[int, int],
    image_cache: dict[tuple[Path, str], np.ndarray],
    warnings: list[str],
) -> np.ndarray:
    if source.kind == "constant":
        arr = _constant(source.value, size)
    else:
        path = material.maps.get(source.map_type or "")
        if path:
            arr = _extract_from_map(path, source.channel, size, image_cache)
        elif source.fallback:
            warnings.append(
                f"{material.name}: missing {source.map_type}; used fallback for a packed channel."
            )
            arr = resolve_channel(source.fallback, material, size, image_cache, warnings)
        else:
            raise ValueError(f"{material.name}: missing required map '{source.map_type}'.")

    if source.invert:
        arr = 255 - arr
    return arr.astype(np.uint8)


def _pack_output(
    output: OutputTexture,
    material: MaterialSet,
    size: tuple[int, int],
    image_cache: dict[tuple[Path, str], np.ndarray],
    warnings: list[str],
) -> Image.Image:
    if output.mode == "L":
        arr = resolve_channel(output.channels["l"], material, size, image_cache, warnings)
        return Image.fromarray(arr, mode="L")

    names = ["r", "g", "b"] if output.mode == "RGB" else ["r", "g", "b", "a"]
    planes = [
        resolve_channel(output.channels[name], material, size, image_cache, warnings)
        for name in names
    ]
    return Image.fromarray(np.dstack(planes).astype(np.uint8), mode=output.mode)


def validate_material(material: MaterialSet, preset: Preset) -> list[str]:
    warnings: list[str] = []
    for output in preset.outputs:
        if _should_skip_output(output, material):
            continue
        for channel_name, source in output.channels.items():
            missing = _missing_required_source(source, material)
            if missing:
                warnings.append(
                    f"{material.name}: {output.label} channel {channel_name.upper()} needs {missing}."
                )
    return warnings


def _should_skip_output(output: OutputTexture, material: MaterialSet) -> bool:
    return bool(output.skip_if_missing) and all(
        map_type not in material.maps for map_type in output.skip_if_missing
    )


def _missing_required_source(source: ChannelSource, material: MaterialSet) -> str | None:
    if source.kind == "constant":
        return None
    if source.map_type in material.maps:
        return None
    if source.fallback:
        return _missing_required_source(source.fallback, material)
    return source.map_type


def pack_material(
    material: MaterialSet,
    preset: Preset,
    output_folder: Path | str,
    *,
    overwrite: bool = True,
    folder_per_material: bool = False,
    game_ready_profile: dict | None = None,
) -> PackResult:
    output_root = Path(output_folder)
    material_folder = output_root / safe_name(material.name) if folder_per_material else output_root
    material_folder.mkdir(parents=True, exist_ok=True)

    warnings = validate_material(material, preset)
    if any(" needs " in warning for warning in warnings):
        raise ValueError("\n".join(warnings))

    size = _target_size(material, preset)
    image_cache: dict[tuple[Path, str], np.ndarray] = {}
    output_paths: list[Path] = []

    for output in preset.outputs:
        if _should_skip_output(output, material):
            warnings.append(
                f"{material.name}: skipped {output.label}; no optional source map was assigned."
            )
            continue
        image = _pack_output(output, material, size, image_cache, warnings)
        path = material_folder / f"{safe_name(material.name)}{output.suffix}.png"
        if path.exists() and not overwrite:
            raise FileExistsError(f"Output already exists: {path}")
        image.save(path, format="PNG", compress_level=4)
        output_paths.append(path)

    write_manifest(material, preset, material_folder, output_paths, warnings, game_ready_profile=game_ready_profile)
    return PackResult(material_name=material.name, output_paths=output_paths, warnings=warnings)


def write_manifest(
    material: MaterialSet,
    preset: Preset,
    output_folder: Path,
    output_paths: list[Path],
    warnings: list[str],
    *,
    game_ready_profile: dict | None = None,
) -> None:
    payload = {
        "material": material.name,
        "preset": {
            "id": preset.id,
            "name": preset.name,
            "engine": preset.engine,
        },
        "inputs": {key: str(path) for key, path in sorted(material.maps.items())},
        "outputs": [str(path) for path in output_paths],
        "import_notes": list(preset.notes),
        "game_ready_profile": game_ready_profile or {},
        "warnings": warnings,
    }
    manifest_path = output_folder / f"{safe_name(material.name)}_manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
