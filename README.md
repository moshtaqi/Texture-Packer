# Material Texture Studio

Material Texture Studio is a modern PyQt6 desktop tool for artists and technical artists who need to detect, preview, validate, and pack material texture maps for engine-ready workflows.

It supports single-material setup, batch conversion, drag-and-drop map assignment, thumbnail previews, preset-driven channel packing, and export manifests.

![Single material workflow](docs/screenshots/single-material.png)

![Batch conversion workflow](docs/screenshots/batch-conversion.png)

## Features

- Detects material texture sets from source folders.
- Supports manual texture assignment with browse buttons and drag-and-drop.
- Shows compact texture thumbnails and color-space hints.
- Provides a Material Health panel with readiness, assigned maps, texture resolution, required-map status, and warnings.
- Batch-scans nested folders and groups materials by source folder.
- Exports packed textures using engine presets.
- Shows export progress, logs, summaries, and an Open Output action after successful export.
- Remembers the last folders, preset, mode, and export options.
- Writes manifest JSON files with inputs, outputs, preset details, import notes, and warnings.

## Export Presets

- **Unreal Engine ORM**
  - BaseColor
  - Normal
  - ORM mask: `R = AO`, `G = Roughness`, `B = Metallic`
  - Optional Height

- **Unity URP Lit**
  - BaseMap
  - Normal
  - URP Mask: `R = Metallic`, `G = Occlusion`, `A = Smoothness`
  - Roughness is inverted into smoothness when smoothness is missing.

- **Unity HDRP Mask Map**
  - BaseColor
  - Normal
  - HDRP MaskMap: `R = Metallic`, `G = AO`, `B = Detail Mask`, `A = Smoothness`

- **Legacy Mobile Two-Texture Pack**
  - Packed Base: `RGB = Base Color`, `A = Roughness`
  - Packed Normal: `R/G = Normal X/Y`, `B = AO`, `A = Height`

## Supported Maps

- Base Color / Albedo
- Normal
- Roughness
- Smoothness / Gloss
- Metallic / Metalness
- Ambient Occlusion
- Height / Displacement
- Opacity / Alpha
- Emissive
- Detail Mask

## Install

Python 3.12+ is recommended.

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
python -m material_texture_studio
```

Alternative launchers are also included:

```powershell
python run_material_texture_studio.py
python texture_channel_packer_pyqt6.py
```

## Test

```powershell
python -m unittest
```

## Project Structure

```text
material_texture_studio/
  detect.py      Texture discovery and material grouping
  packer.py      Channel packing and export manifests
  presets.py     Map definitions and export presets
  preview.py     Thumbnail generation
  models.py      Data structures
  main.py        PyQt6 desktop UI
tests/
  test_packer.py
docs/screenshots/
  single-material.png
  batch-conversion.png
```

## Packaging Notes

The app uses a bundled Comfortaa font and `texture_packer_icon.ico` for the window icon. When packaging as an executable, include:

- `material_texture_studio/assets/fonts/Comfortaa.ttf`
- `texture_packer_icon.ico`
- Pillow and NumPy runtime dependencies
- PyQt6 platform plugins

For PyInstaller, start with:

```powershell
pyinstaller --noconsole --name "Material Texture Studio" --icon texture_packer_icon.ico --add-data "material_texture_studio/assets/fonts/Comfortaa.ttf;material_texture_studio/assets/fonts" --add-data "texture_packer_icon.ico;." run_material_texture_studio.py
```
