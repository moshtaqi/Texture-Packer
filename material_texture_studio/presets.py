from __future__ import annotations

from material_texture_studio.models import ChannelSource as S
from material_texture_studio.models import MapType, OutputTexture, Preset


MAP_TYPES: dict[str, MapType] = {
    "base_color": MapType(
        key="base_color",
        label="Base Color / Albedo",
        optional=False,
        color_space="sRGB",
        keywords=(
            "basecolor",
            "base_color",
            "base color",
            "albedo",
            "alb",
            "diff",
            "diffuse",
            "basecolour",
            "base_colour",
            "color",
            "colour",
            "col",
            "base",
            "bc",
        ),
    ),
    "normal": MapType(
        key="normal",
        label="Normal",
        optional=False,
        color_space="Linear",
        keywords=("normal", "normalgl", "normaldx", "normalmap", "norm", "nrm", "nor", "bumpnormal"),
    ),
    "roughness": MapType(
        key="roughness",
        label="Roughness",
        optional=True,
        color_space="Linear",
        keywords=("roughness", "roughnessmap", "rough", "rgh"),
    ),
    "smoothness": MapType(
        key="smoothness",
        label="Smoothness / Gloss",
        optional=True,
        color_space="Linear",
        keywords=("smoothness", "smoothnessmap", "smooth", "glossiness", "gloss", "specgloss"),
    ),
    "metallic": MapType(
        key="metallic",
        label="Metallic / Metalness",
        optional=True,
        color_space="Linear",
        keywords=("metallic", "metallicmap", "metalness", "metal", "mtl"),
    ),
    "ao": MapType(
        key="ao",
        label="Ambient Occlusion",
        optional=True,
        color_space="Linear",
        keywords=("ambientocclusion", "ambient_occlusion", "ambient occlusion", "occlusion", "occlusionmap", "ao"),
    ),
    "height": MapType(
        key="height",
        label="Height / Displacement",
        optional=True,
        color_space="Linear",
        keywords=("height", "heightmap", "displacement", "displace", "disp", "depth", "bump"),
    ),
    "opacity": MapType(
        key="opacity",
        label="Opacity / Alpha",
        optional=True,
        color_space="Linear",
        keywords=("opacity", "opacitymap", "alpha", "transparency", "translucency", "cutout"),
    ),
    "emissive": MapType(
        key="emissive",
        label="Emissive",
        optional=True,
        color_space="sRGB",
        keywords=("emissive", "emission", "emit"),
    ),
    "detail_mask": MapType(
        key="detail_mask",
        label="Detail Mask",
        optional=True,
        color_space="Linear",
        keywords=("detailmask", "detail_mask", "detail", "mask"),
    ),
}


def _base_color_output(suffix: str = "_BaseColor") -> OutputTexture:
    return OutputTexture(
        key="base_color",
        label="Base Color",
        suffix=suffix,
        mode="RGB",
        color_space="sRGB",
        channels={
            "r": S.map("base_color", "r"),
            "g": S.map("base_color", "g"),
            "b": S.map("base_color", "b"),
        },
        description="Color texture. Import as sRGB.",
    )


def _base_map_output(suffix: str = "_BaseMap") -> OutputTexture:
    return OutputTexture(
        key="base_map",
        label="Base Map",
        suffix=suffix,
        mode="RGBA",
        color_space="sRGB",
        channels={
            "r": S.map("base_color", "r"),
            "g": S.map("base_color", "g"),
            "b": S.map("base_color", "b"),
            "a": S.map("opacity", "gray", fallback=S.constant(255)),
        },
        description="Unity base map. RGB is color, alpha is opacity.",
    )


def _normal_output(suffix: str = "_Normal") -> OutputTexture:
    return OutputTexture(
        key="normal",
        label="Normal",
        suffix=suffix,
        mode="RGB",
        color_space="Linear",
        channels={
            "r": S.map("normal", "r"),
            "g": S.map("normal", "g"),
            "b": S.map("normal", "b"),
        },
        description="Normal map. Import as a normal texture, not sRGB color.",
    )


PRESETS: dict[str, Preset] = {
    "unreal_orm": Preset(
        id="unreal_orm",
        name="Unreal Engine ORM",
        engine="Unreal Engine",
        description="Exports BaseColor, Normal, and an ORM mask: R=AO, G=Roughness, B=Metallic.",
        normal_y="directx",
        outputs=(
            _base_color_output("_BaseColor"),
            _normal_output("_Normal"),
            OutputTexture(
                key="orm",
                label="ORM Mask",
                suffix="_ORM",
                mode="RGB",
                color_space="Linear",
                channels={
                    "r": S.map("ao", "gray", fallback=S.constant(255)),
                    "g": S.map("roughness", "gray", fallback=S.constant(128)),
                    "b": S.map("metallic", "gray", fallback=S.constant(0)),
                },
                description="Unreal mask texture. Disable sRGB. R=AO, G=Roughness, B=Metallic.",
            ),
            OutputTexture(
                key="height",
                label="Height",
                suffix="_Height",
                mode="L",
                color_space="Linear",
                channels={"l": S.map("height", "gray", fallback=S.constant(128))},
                description="Optional height output for displacement/parallax workflows.",
                skip_if_missing=("height",),
            ),
        ),
        notes=(
            "Packed mask textures should usually import with sRGB disabled.",
            "Unreal commonly uses DirectX-style normal maps.",
        ),
    ),
    "unity_urp": Preset(
        id="unity_urp",
        name="Unity URP Lit",
        engine="Unity",
        description="Exports BaseMap, Normal, and a URP mask: R=Metallic, G=Occlusion, A=Smoothness.",
        normal_y="unchanged",
        outputs=(
            _base_map_output("_BaseMap"),
            _normal_output("_Normal"),
            OutputTexture(
                key="mask",
                label="URP Mask",
                suffix="_Mask",
                mode="RGBA",
                color_space="Linear",
                channels={
                    "r": S.map("metallic", "gray", fallback=S.constant(0)),
                    "g": S.map("ao", "gray", fallback=S.constant(255)),
                    "b": S.constant(0),
                    "a": S.map(
                        "smoothness",
                        "gray",
                        fallback=S.map("roughness", "gray", invert=True, fallback=S.constant(128)),
                    ),
                },
                description="Unity URP packed texture. Disable sRGB. A uses smoothness; roughness is inverted if needed.",
            ),
        ),
        notes=(
            "Unity URP packed masks use smoothness, not roughness.",
            "If only roughness exists, this preset inverts it into smoothness.",
        ),
    ),
    "unity_hdrp": Preset(
        id="unity_hdrp",
        name="Unity HDRP Mask Map",
        engine="Unity",
        description="Exports BaseColor, Normal, and HDRP MaskMap: R=Metallic, G=AO, B=Detail, A=Smoothness.",
        normal_y="unchanged",
        outputs=(
            _base_color_output("_BaseColor"),
            _normal_output("_Normal"),
            OutputTexture(
                key="mask_map",
                label="HDRP Mask Map",
                suffix="_MaskMap",
                mode="RGBA",
                color_space="Linear",
                channels={
                    "r": S.map("metallic", "gray", fallback=S.constant(0)),
                    "g": S.map("ao", "gray", fallback=S.constant(255)),
                    "b": S.map("detail_mask", "gray", fallback=S.constant(0)),
                    "a": S.map(
                        "smoothness",
                        "gray",
                        fallback=S.map("roughness", "gray", invert=True, fallback=S.constant(128)),
                    ),
                },
                description="Unity HDRP mask map. Disable sRGB.",
            ),
        ),
        notes=(
            "HDRP MaskMap blue is a detail mask. It safely defaults to black.",
            "Smoothness is packed into alpha.",
        ),
    ),
    "godot_orm": Preset(
        id="godot_orm",
        name="Godot ORM",
        engine="Godot",
        description="Exports Albedo, Normal, and an ORM texture: R=AO, G=Roughness, B=Metallic.",
        normal_y="opengl",
        outputs=(
            _base_color_output("_Albedo"),
            _normal_output("_Normal"),
            OutputTexture(
                key="orm",
                label="ORM Texture",
                suffix="_ORM",
                mode="RGB",
                color_space="Linear",
                channels={
                    "r": S.map("ao", "gray", fallback=S.constant(255)),
                    "g": S.map("roughness", "gray", fallback=S.constant(128)),
                    "b": S.map("metallic", "gray", fallback=S.constant(0)),
                },
                description="Godot ORM texture. Use as occlusion/roughness/metallic data, not sRGB color.",
            ),
        ),
        notes=(
            "Godot ORM uses AO in red, roughness in green, and metallic in blue.",
            "OpenGL-style normal maps are common in Godot workflows.",
        ),
    ),
    "gltf_metallic_roughness": Preset(
        id="gltf_metallic_roughness",
        name="glTF Metallic-Roughness",
        engine="glTF",
        description="Exports BaseColor, Normal, and glTF MR packing: G=Roughness, B=Metallic.",
        normal_y="opengl",
        outputs=(
            _base_map_output("_BaseColor"),
            _normal_output("_Normal"),
            OutputTexture(
                key="metallic_roughness",
                label="Metallic Roughness",
                suffix="_MetallicRoughness",
                mode="RGB",
                color_space="Linear",
                channels={
                    "r": S.constant(255),
                    "g": S.map("roughness", "gray", fallback=S.constant(128)),
                    "b": S.map("metallic", "gray", fallback=S.constant(0)),
                },
                description="glTF metallic-roughness texture. Green=roughness, blue=metallic.",
            ),
            OutputTexture(
                key="occlusion",
                label="Occlusion",
                suffix="_Occlusion",
                mode="L",
                color_space="Linear",
                channels={"l": S.map("ao", "gray", fallback=S.constant(255))},
                description="Optional glTF occlusion texture.",
                skip_if_missing=("ao",),
            ),
        ),
        notes=(
            "glTF metallic-roughness uses roughness in green and metallic in blue.",
            "Occlusion is usually stored as a separate texture in glTF pipelines.",
        ),
    ),
    "legacy_mobile": Preset(
        id="legacy_mobile",
        name="Legacy Mobile Two-Texture Pack",
        engine="Custom",
        description="Matches the old prototype: Base RGB + Roughness A, Normal RG + AO B + Height A.",
        normal_y="unchanged",
        outputs=(
            OutputTexture(
                key="packed_base",
                label="Packed Base",
                suffix="_Packed_BaseColor",
                mode="RGBA",
                color_space="sRGB RGB / Linear A",
                channels={
                    "r": S.map("base_color", "r"),
                    "g": S.map("base_color", "g"),
                    "b": S.map("base_color", "b"),
                    "a": S.map("roughness", "gray", fallback=S.constant(128)),
                },
                description="RGB color with roughness in alpha.",
            ),
            OutputTexture(
                key="packed_normal",
                label="Packed Normal",
                suffix="_Packed_Normal",
                mode="RGBA",
                color_space="Linear",
                channels={
                    "r": S.map("normal", "r"),
                    "g": S.map("normal", "g"),
                    "b": S.map("ao", "gray", fallback=S.constant(255)),
                    "a": S.map("height", "gray", fallback=S.constant(255)),
                },
                description="Normal RG with AO in blue and height in alpha.",
            ),
        ),
        notes=("Kept for projects already using the original packing convention.",),
    ),
}


def ordered_map_types_for_preset(preset: Preset) -> list[MapType]:
    preferred = [
        "base_color",
        "normal",
        "roughness",
        "smoothness",
        "metallic",
        "ao",
        "height",
        "opacity",
        "detail_mask",
        "emissive",
    ]
    used = preset.map_types()
    return [MAP_TYPES[key] for key in preferred if key in used]
