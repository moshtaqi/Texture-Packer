from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ChannelName = Literal["r", "g", "b", "a", "gray"]
OutputMode = Literal["RGB", "RGBA", "L"]
SourceKind = Literal["map", "constant"]


@dataclass(frozen=True)
class MapType:
    key: str
    label: str
    optional: bool = True
    color_space: str = "Linear"
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChannelSource:
    kind: SourceKind
    map_type: str | None = None
    channel: ChannelName = "gray"
    value: int = 255
    invert: bool = False
    fallback: "ChannelSource | None" = None

    @staticmethod
    def map(
        map_type: str,
        channel: ChannelName = "gray",
        *,
        invert: bool = False,
        fallback: "ChannelSource | None" = None,
    ) -> "ChannelSource":
        return ChannelSource(
            kind="map",
            map_type=map_type,
            channel=channel,
            invert=invert,
            fallback=fallback,
        )

    @staticmethod
    def constant(value: int = 255, *, invert: bool = False) -> "ChannelSource":
        return ChannelSource(kind="constant", value=value, invert=invert)


@dataclass(frozen=True)
class OutputTexture:
    key: str
    label: str
    suffix: str
    mode: OutputMode
    color_space: str
    channels: dict[str, ChannelSource]
    description: str = ""
    skip_if_missing: tuple[str, ...] = ()

    def required_maps(self) -> set[str]:
        found: set[str] = set()

        def visit(source: ChannelSource) -> None:
            if source.kind == "map" and source.map_type:
                found.add(source.map_type)
            if source.fallback:
                visit(source.fallback)

        for source in self.channels.values():
            visit(source)

        return found


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    engine: str
    description: str
    outputs: tuple[OutputTexture, ...]
    notes: tuple[str, ...] = ()
    normal_y: Literal["directx", "opengl", "unchanged"] = "unchanged"

    def map_types(self) -> set[str]:
        result: set[str] = set()
        for output in self.outputs:
            result.update(output.required_maps())
        return result


@dataclass
class MaterialSet:
    name: str
    maps: dict[str, Path] = field(default_factory=dict)
    source_folder: Path | None = None

    def copy(self) -> "MaterialSet":
        return MaterialSet(
            name=self.name,
            maps=dict(self.maps),
            source_folder=self.source_folder,
        )


@dataclass
class PackResult:
    material_name: str
    output_paths: list[Path]
    warnings: list[str]


IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".tga",
    ".webp",
}
