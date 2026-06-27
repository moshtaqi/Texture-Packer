from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from material_texture_studio.detect import detect_material_sets, detect_material_sets_by_folder
from material_texture_studio.models import MaterialSet
from material_texture_studio.packer import pack_material
from material_texture_studio.presets import PRESETS


def write_rgb(path: Path, color: tuple[int, int, int]) -> None:
    arr = np.zeros((4, 4, 3), dtype=np.uint8)
    arr[:, :] = color
    Image.fromarray(arr, mode="RGB").save(path)


def write_gray(path: Path, value: int) -> None:
    arr = np.full((4, 4), value, dtype=np.uint8)
    Image.fromarray(arr, mode="L").save(path)


class PackerTests(unittest.TestCase):
    def test_unreal_orm_channel_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            base = folder / "Stone_BaseColor.png"
            normal = folder / "Stone_Normal.png"
            rough = folder / "Stone_Roughness.png"
            metal = folder / "Stone_Metallic.png"
            ao = folder / "Stone_AO.png"

            write_rgb(base, (10, 20, 30))
            write_rgb(normal, (128, 128, 255))
            write_gray(rough, 64)
            write_gray(metal, 32)
            write_gray(ao, 200)

            result = pack_material(
                MaterialSet(
                    name="Stone",
                    maps={
                        "base_color": base,
                        "normal": normal,
                        "roughness": rough,
                        "metallic": metal,
                        "ao": ao,
                    },
                ),
                PRESETS["unreal_orm"],
                folder / "out",
            )

            orm_path = next(path for path in result.output_paths if path.name.endswith("_ORM.png"))
            arr = np.asarray(Image.open(orm_path).convert("RGB"))
            self.assertEqual(tuple(arr[0, 0]), (200, 64, 32))

    def test_unity_roughness_becomes_smoothness_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            base = folder / "Mud_BaseColor.png"
            normal = folder / "Mud_Normal.png"
            rough = folder / "Mud_Roughness.png"

            write_rgb(base, (12, 24, 36))
            write_rgb(normal, (128, 128, 255))
            write_gray(rough, 40)

            result = pack_material(
                MaterialSet(
                    name="Mud",
                    maps={"base_color": base, "normal": normal, "roughness": rough},
                ),
                PRESETS["unity_urp"],
                folder / "out",
            )

            mask_path = next(path for path in result.output_paths if path.name.endswith("_Mask.png"))
            arr = np.asarray(Image.open(mask_path).convert("RGBA"))
            self.assertEqual(tuple(arr[0, 0]), (0, 255, 0, 215))

    def test_blender_style_aliases_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_rgb(folder / "Moss_diff.png", (1, 2, 3))
            write_rgb(folder / "Moss_nrm.png", (128, 128, 255))
            write_gray(folder / "Moss_rough.png", 90)
            write_gray(folder / "Moss_metalness.png", 0)
            write_gray(folder / "Moss_ao.png", 220)

            materials = detect_material_sets(folder, recursive=False)

            self.assertEqual(len(materials), 1)
            self.assertEqual(materials[0].name, "Moss")
            self.assertEqual(
                set(materials[0].maps),
                {"base_color", "normal", "roughness", "metallic", "ao"},
            )

    def test_recursive_batch_groups_by_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rock = root / "Rock"
            soil = root / "Soil"
            rock.mkdir()
            soil.mkdir()
            write_rgb(rock / "BaseColor.png", (1, 2, 3))
            write_rgb(rock / "Normal.png", (128, 128, 255))
            write_rgb(soil / "Soil_Albedo.png", (4, 5, 6))
            write_rgb(soil / "Soil_Normal.png", (128, 128, 255))

            materials = detect_material_sets_by_folder(root)

            self.assertEqual([material.name for material in materials], ["Rock", "Soil"])
            self.assertEqual({material.source_folder.name for material in materials}, {"Rock", "Soil"})


if __name__ == "__main__":
    unittest.main()
