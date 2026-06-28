from __future__ import annotations

import csv
import html
import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from material_texture_studio.models import MaterialSet, OutputTexture, Preset
from material_texture_studio.presets import MAP_TYPES


NAMING_PROFILES = {
    "default": {
        "name": "Default",
        "template": "{material}{suffix}",
        "example": "Rock_ORM.png",
    },
    "unreal": {
        "name": "Unreal T_ Prefix",
        "template": "T_{material}{suffix}",
        "example": "T_Rock_ORM.png",
    },
    "unity": {
        "name": "Unity Clean",
        "template": "{material}{suffix}",
        "example": "Rock_MaskMap.png",
    },
    "studio": {
        "name": "Studio Asset Descriptor",
        "template": "TEX_{material}{suffix}",
        "example": "TEX_Rock_ORM.png",
    },
    "custom": {
        "name": "Custom Template",
        "template": "{material}{suffix}",
        "example": "{material}{suffix}.png",
    },
}

IMPORT_TARGETS = {
    "unreal": "Unreal Python",
    "unity": "Unity Editor C#",
    "godot": "Godot Notes",
}


def safe_name(text: str, fallback: str = "Material") -> str:
    text = text.strip() or fallback
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    return text.strip("._ ") or fallback


@dataclass
class PipelineOptions:
    naming_profile: str = "default"
    naming_template: str = "{material}{suffix}"
    max_size: int = 0
    force_power_of_two: bool = False
    generate_mipmap_metadata: bool = True
    import_targets: tuple[str, ...] = ()
    ocio_config: str = ""
    color_audit: bool = True
    detect_udim: bool = True
    atlas_preview: bool = False
    texture_transform_metadata: bool = True
    html_report: bool = True
    csv_report: bool = True
    usd_sidecar: bool = True
    materialx_sidecar: bool = True
    ktx2_mode: str = "plan"
    ktx2_tool_path: str = ""
    memory_budget_mb: int = 256
    compression_profile: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(data: dict | None) -> "PipelineOptions":
        if not data:
            return PipelineOptions()
        import_targets = data.get("import_targets", ())
        if isinstance(import_targets, list):
            import_targets = tuple(import_targets)
        return PipelineOptions(
            naming_profile=str(data.get("naming_profile", "default")),
            naming_template=str(data.get("naming_template", "{material}{suffix}")),
            max_size=int(data.get("max_size") or 0),
            force_power_of_two=bool(data.get("force_power_of_two", False)),
            generate_mipmap_metadata=bool(data.get("generate_mipmap_metadata", True)),
            import_targets=tuple(import_targets),
            ocio_config=str(data.get("ocio_config", "")),
            color_audit=bool(data.get("color_audit", True)),
            detect_udim=bool(data.get("detect_udim", True)),
            atlas_preview=bool(data.get("atlas_preview", False)),
            texture_transform_metadata=bool(data.get("texture_transform_metadata", True)),
            html_report=bool(data.get("html_report", True)),
            csv_report=bool(data.get("csv_report", True)),
            usd_sidecar=bool(data.get("usd_sidecar", True)),
            materialx_sidecar=bool(data.get("materialx_sidecar", True)),
            ktx2_mode=str(data.get("ktx2_mode", "plan")),
            ktx2_tool_path=str(data.get("ktx2_tool_path", "")),
            memory_budget_mb=int(data.get("memory_budget_mb") or 256),
            compression_profile=dict(data.get("compression_profile") or {}),
        )

    def to_dict(self) -> dict:
        return {
            "naming_profile": self.naming_profile,
            "naming_template": self.naming_template,
            "max_size": self.max_size,
            "force_power_of_two": self.force_power_of_two,
            "generate_mipmap_metadata": self.generate_mipmap_metadata,
            "import_targets": list(self.import_targets),
            "ocio_config": self.ocio_config,
            "color_audit": self.color_audit,
            "detect_udim": self.detect_udim,
            "atlas_preview": self.atlas_preview,
            "texture_transform_metadata": self.texture_transform_metadata,
            "html_report": self.html_report,
            "csv_report": self.csv_report,
            "usd_sidecar": self.usd_sidecar,
            "materialx_sidecar": self.materialx_sidecar,
            "ktx2_mode": self.ktx2_mode,
            "ktx2_tool_path": self.ktx2_tool_path,
            "memory_budget_mb": self.memory_budget_mb,
            "compression_profile": self.compression_profile,
        }


def output_stem(material: MaterialSet, output: OutputTexture, options: PipelineOptions | None = None) -> str:
    options = options or PipelineOptions()
    template = options.naming_template or NAMING_PROFILES.get(options.naming_profile, NAMING_PROFILES["default"])["template"]
    if options.naming_profile != "custom":
        template = NAMING_PROFILES.get(options.naming_profile, NAMING_PROFILES["default"])["template"]
    stem = template.format(
        material=safe_name(material.name),
        suffix=output.suffix,
        output=safe_name(output.label),
        engine=safe_name(""),
    )
    return safe_name(stem)


def target_size_with_options(size: tuple[int, int], options: PipelineOptions | None = None) -> tuple[int, int]:
    options = options or PipelineOptions()
    width, height = size
    if options.max_size and max(width, height) > options.max_size:
        scale = options.max_size / max(width, height)
        width = max(1, int(round(width * scale)))
        height = max(1, int(round(height * scale)))
    if options.force_power_of_two:
        width = nearest_power_of_two(width)
        height = nearest_power_of_two(height)
    return width, height


def nearest_power_of_two(value: int) -> int:
    if value <= 1:
        return 1
    lower = 2 ** int(math.floor(math.log2(value)))
    upper = 2 ** int(math.ceil(math.log2(value)))
    return lower if value - lower <= upper - value else upper


def collect_pipeline_metadata(
    material: MaterialSet,
    preset: Preset,
    output_paths: list[Path],
    warnings: list[str],
    options: PipelineOptions,
) -> dict:
    inputs = input_metadata(material)
    outputs = output_metadata(output_paths, options)
    memory = memory_summary(outputs, options)
    udim = detect_udim_tiles(material) if options.detect_udim else {}
    color = color_audit(material, preset, options) if options.color_audit else []
    atlas = write_atlas_preview(material, output_paths[0].parent) if options.atlas_preview and output_paths else {}
    transforms = texture_transform_metadata(output_paths) if options.texture_transform_metadata else {}
    ktx2 = handle_ktx2(output_paths, options)
    generated = write_pipeline_sidecars(
        material,
        preset,
        output_paths,
        options,
        inputs=inputs,
        outputs=outputs,
        memory=memory,
        udim=udim,
        color=color,
        atlas=atlas,
        transforms=transforms,
        ktx2=ktx2,
        warnings=warnings,
    )
    return {
        "options": options.to_dict(),
        "inputs": inputs,
        "outputs": outputs,
        "memory": memory,
        "udim": udim,
        "color_audit": color,
        "atlas": atlas,
        "texture_transforms": transforms,
        "ktx2": ktx2,
        "generated_pipeline_files": [str(path) for path in generated],
    }


def input_metadata(material: MaterialSet) -> dict:
    result = {}
    for key, path in sorted(material.maps.items()):
        meta = {"path": str(path), "role": key}
        try:
            with Image.open(path) as image:
                meta.update({"width": image.width, "height": image.height, "mode": image.mode})
        except Exception as exc:
            meta["error"] = str(exc)
        result[key] = meta
    return result


def output_metadata(paths: list[Path], options: PipelineOptions) -> list[dict]:
    result = []
    for path in paths:
        meta = {"path": str(path), "name": path.name}
        try:
            with Image.open(path) as image:
                meta.update(
                    {
                        "width": image.width,
                        "height": image.height,
                        "mode": image.mode,
                        "estimated_vram": estimate_texture_memory(image.width, image.height, image.mode),
                    }
                )
        except Exception as exc:
            meta["error"] = str(exc)
        result.append(meta)
    return result


def estimate_texture_memory(width: int, height: int, mode: str, *, mipmaps: bool = True) -> dict:
    channels = {"L": 1, "RGB": 3, "RGBA": 4}.get(mode, 4)
    uncompressed = width * height * channels
    mip_factor = 4 / 3 if mipmaps else 1
    bc1 = width * height * 0.5 * mip_factor
    bc5 = width * height * 1.0 * mip_factor
    bc7 = width * height * 1.0 * mip_factor
    astc_6x6 = width * height * (16 / 36) * mip_factor
    return {
        "uncompressed_mb": round(uncompressed * mip_factor / (1024 * 1024), 2),
        "bc1_mb": round(bc1 / (1024 * 1024), 2),
        "bc5_mb": round(bc5 / (1024 * 1024), 2),
        "bc7_mb": round(bc7 / (1024 * 1024), 2),
        "astc_6x6_mb": round(astc_6x6 / (1024 * 1024), 2),
    }


def memory_summary(outputs: list[dict], options: PipelineOptions) -> dict:
    totals = {"uncompressed_mb": 0.0, "bc1_mb": 0.0, "bc5_mb": 0.0, "bc7_mb": 0.0, "astc_6x6_mb": 0.0}
    for output in outputs:
        for key, value in output.get("estimated_vram", {}).items():
            totals[key] = round(totals.get(key, 0.0) + float(value), 2)
    return {
        "budget_mb": options.memory_budget_mb,
        "totals": totals,
        "over_budget": totals["uncompressed_mb"] > options.memory_budget_mb,
    }


def detect_udim_tiles(material: MaterialSet) -> dict:
    if not material.source_folder:
        return {}
    pattern = re.compile(r"(?<!\d)(1\d{3})(?!\d)")
    found: dict[str, dict[str, str]] = {}
    for path in material.source_folder.glob("*"):
        if not path.is_file():
            continue
        match = pattern.search(path.stem)
        if not match:
            continue
        tile = match.group(1)
        role = "unknown"
        for key in MAP_TYPES:
            if key in material.maps and material.maps[key].name == path.name:
                role = key
                break
        found.setdefault(tile, {})[role] = str(path)
    tiles = sorted(found)
    gaps = []
    if tiles:
        numeric = [int(tile) for tile in tiles]
        gaps = [str(tile) for tile in range(min(numeric), max(numeric) + 1) if str(tile) not in found]
    return {"tiles": found, "tile_count": len(found), "missing_between_min_max": gaps}


def color_audit(material: MaterialSet, preset: Preset, options: PipelineOptions) -> list[dict]:
    entries = []
    for key, path in sorted(material.maps.items()):
        info = MAP_TYPES.get(key)
        expected = info.color_space if info else "Linear"
        entries.append(
            {
                "map": key,
                "file": str(path),
                "expected_color_space": expected,
                "ocio_config": options.ocio_config,
                "note": "Treat as display color." if expected == "sRGB" else "Treat as data/linear texture.",
            }
        )
    return entries


def write_atlas_preview(material: MaterialSet, output_folder: Path) -> dict:
    if not material.maps:
        return {}
    cell = 160
    columns = min(4, max(1, len(material.maps)))
    rows = math.ceil(len(material.maps) / columns)
    atlas = Image.new("RGB", (columns * cell, rows * cell), (16, 22, 29))
    draw = ImageDraw.Draw(atlas)
    for index, (key, path) in enumerate(sorted(material.maps.items())):
        x = (index % columns) * cell
        y = (index // columns) * cell
        try:
            with Image.open(path) as image:
                thumb = image.convert("RGB")
                thumb.thumbnail((cell - 16, cell - 34), Image.Resampling.LANCZOS)
                atlas.paste(thumb, (x + 8, y + 8))
        except Exception:
            pass
        draw.text((x + 8, y + cell - 22), key, fill=(232, 238, 245))
    path = output_folder / f"{safe_name(material.name)}_atlas_preview.png"
    atlas.save(path, "PNG")
    return {"preview": str(path), "cell_size": cell, "columns": columns, "rows": rows}


def texture_transform_metadata(paths: list[Path]) -> dict:
    return {
        path.name: {
            "offset": [0.0, 0.0],
            "scale": [1.0, 1.0],
            "rotation": 0.0,
            "gltf_extension": "KHR_texture_transform",
        }
        for path in paths
    }


def handle_ktx2(output_paths: list[Path], options: PipelineOptions) -> dict:
    if options.ktx2_mode == "off":
        return {"mode": "off"}
    tool = options.ktx2_tool_path.strip() or shutil.which("basisu") or shutil.which("toktx") or ""
    commands = []
    generated = []
    for path in output_paths:
        ktx2_path = path.with_suffix(".ktx2")
        command = [tool or "basisu", "-ktx2", str(path), "-output_file", str(ktx2_path)]
        commands.append(" ".join(command))
        if options.ktx2_mode == "run" and tool:
            try:
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
                if ktx2_path.exists():
                    generated.append(str(ktx2_path))
            except Exception as exc:
                return {"mode": "run", "tool": tool, "commands": commands, "generated": generated, "error": str(exc)}
    if output_paths:
        plan_path = output_paths[0].parent / f"{safe_name(output_paths[0].stem)}_ktx2_commands.txt"
        plan_path.write_text("\n".join(commands), encoding="utf-8")
    return {
        "mode": options.ktx2_mode,
        "tool": tool or "basisu",
        "commands": commands,
        "generated": generated,
        "note": "Install basisu or toktx and use Run mode for automatic KTX2 output." if not tool else "",
    }


def write_pipeline_sidecars(
    material: MaterialSet,
    preset: Preset,
    output_paths: list[Path],
    options: PipelineOptions,
    **payload,
) -> list[Path]:
    if not output_paths:
        return []
    folder = output_paths[0].parent
    stem = safe_name(material.name)
    generated: list[Path] = []
    report_payload = {"material": material.name, "preset": preset.name, **payload}

    if options.html_report:
        path = folder / f"{stem}_pipeline_report.html"
        path.write_text(render_html_report(report_payload), encoding="utf-8")
        generated.append(path)
    if options.csv_report:
        path = folder / f"{stem}_pipeline_report.csv"
        write_csv_report(path, report_payload)
        generated.append(path)
    if options.usd_sidecar:
        path = folder / f"{stem}_usd_sidecar.json"
        path.write_text(json.dumps(render_usd_sidecar(material, preset, output_paths, report_payload), indent=2), encoding="utf-8")
        generated.append(path)
    if options.materialx_sidecar:
        path = folder / f"{stem}_materialx_sidecar.json"
        path.write_text(json.dumps(render_materialx_sidecar(material, preset, output_paths, report_payload), indent=2), encoding="utf-8")
        generated.append(path)
    if payload.get("udim"):
        path = folder / f"{stem}_udim_tiles.json"
        path.write_text(json.dumps(payload["udim"], indent=2), encoding="utf-8")
        generated.append(path)
    if payload.get("transforms"):
        path = folder / f"{stem}_texture_transforms.json"
        path.write_text(json.dumps(payload["transforms"], indent=2), encoding="utf-8")
        generated.append(path)
    for target in options.import_targets:
        script = write_import_helper(folder, material, preset, output_paths, target)
        if script:
            generated.append(script)
    return generated


def render_html_report(payload: dict) -> str:
    rows = []
    for output in payload.get("outputs", []):
        memory = output.get("estimated_vram", {})
        rows.append(
            "<tr>"
            f"<td>{html.escape(output.get('name', ''))}</td>"
            f"<td>{output.get('width', '')}x{output.get('height', '')}</td>"
            f"<td>{html.escape(output.get('mode', ''))}</td>"
            f"<td>{memory.get('bc7_mb', '')} MB BC7</td>"
            "</tr>"
        )
    warnings = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in payload.get("warnings", []))
    color = "".join(
        f"<li>{html.escape(item['map'])}: {html.escape(item['expected_color_space'])}</li>"
        for item in payload.get("color", [])
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Pipeline Report</title>"
        "<style>body{font-family:Arial;background:#10161d;color:#e8eef5;padding:24px}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #2a3440;padding:8px}"
        "th{background:#1b222b}</style></head><body>"
        f"<h1>{html.escape(payload.get('material', 'Material'))}</h1>"
        f"<p>Preset: {html.escape(payload.get('preset', ''))}</p>"
        "<h2>Outputs</h2><table><tr><th>Name</th><th>Size</th><th>Mode</th><th>Memory</th></tr>"
        + "".join(rows)
        + "</table><h2>Color Audit</h2><ul>"
        + color
        + "</ul><h2>Warnings</h2><ul>"
        + warnings
        + "</ul></body></html>"
    )


def write_csv_report(path: Path, payload: dict) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["material", "preset", "output", "width", "height", "mode", "uncompressed_mb", "bc7_mb", "astc_6x6_mb"])
        for output in payload.get("outputs", []):
            memory = output.get("estimated_vram", {})
            writer.writerow(
                [
                    payload.get("material", ""),
                    payload.get("preset", ""),
                    output.get("name", ""),
                    output.get("width", ""),
                    output.get("height", ""),
                    output.get("mode", ""),
                    memory.get("uncompressed_mb", ""),
                    memory.get("bc7_mb", ""),
                    memory.get("astc_6x6_mb", ""),
                ]
            )


def render_usd_sidecar(material: MaterialSet, preset: Preset, output_paths: list[Path], payload: dict) -> dict:
    return {
        "schema": "MaterialTextureStudio.OpenUSDSidecar.v1",
        "material": material.name,
        "preset": preset.name,
        "texture_roles": {path.stem: str(path) for path in output_paths},
        "pbr_workflow": "metallic_roughness",
        "color_audit": payload.get("color", []),
        "udim": payload.get("udim", {}),
    }


def render_materialx_sidecar(material: MaterialSet, preset: Preset, output_paths: list[Path], payload: dict) -> dict:
    return {
        "schema": "MaterialTextureStudio.MaterialXSidecar.v1",
        "material": material.name,
        "preset": preset.name,
        "textures": [{"file": str(path), "role": path.stem} for path in output_paths],
        "color_audit": payload.get("color", []),
    }


def write_import_helper(folder: Path, material: MaterialSet, preset: Preset, output_paths: list[Path], target: str) -> Path | None:
    stem = safe_name(material.name)
    if target == "unreal":
        path = folder / f"{stem}_unreal_import.py"
        path.write_text(render_unreal_import_script(output_paths), encoding="utf-8")
        return path
    if target == "unity":
        path = folder / f"{stem}_UnityTextureImportSettings.cs"
        path.write_text(render_unity_import_script(output_paths), encoding="utf-8")
        return path
    if target == "godot":
        path = folder / f"{stem}_godot_import_notes.txt"
        path.write_text(render_godot_notes(output_paths), encoding="utf-8")
        return path
    return None


def render_unreal_import_script(output_paths: list[Path]) -> str:
    lines = [
        "import unreal",
        "",
        "# Run in Unreal's Python console after importing these textures.",
        "paths = [",
    ]
    lines.extend(f"    r'{path}'," for path in output_paths)
    lines.extend(
        [
            "]",
            "for path in paths:",
            "    asset_name = path.rsplit('\\\\', 1)[-1].rsplit('/', 1)[-1]",
            "    print(f'Configure texture import settings for {asset_name}')",
            "    # BaseColor: sRGB on. Normal: compression normal map. Masks: sRGB off.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_unity_import_script(output_paths: list[Path]) -> str:
    names = ", ".join(f'\"{path.name}\"' for path in output_paths)
    return f"""using UnityEditor;
using UnityEngine;

public static class MaterialTextureStudioImportSettings
{{
    [MenuItem("Tools/Material Texture Studio/Print Import Checklist")]
    public static void PrintChecklist()
    {{
        string[] textures = new string[] {{ {names} }};
        foreach (string texture in textures)
        {{
            Debug.Log($"Check import settings for {{texture}}: BaseMap sRGB, Normal as normal map, packed masks linear.");
        }}
    }}
}}
"""


def render_godot_notes(output_paths: list[Path]) -> str:
    lines = ["Godot import notes:", "Use albedo as color, normal as normal, ORM as occlusion/roughness/metallic data.", ""]
    lines.extend(str(path) for path in output_paths)
    return "\n".join(lines) + "\n"
