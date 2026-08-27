"""Video metadata helpers for Civitai-compatible Image Saver output."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable


MAX_METADATA_VALUE_BYTES = 2 * 1024 * 1024


def extract_json_after(text: str, marker: str) -> Any | None:
    """Decode the first JSON value following ``marker``."""
    if not text:
        return None

    marker_position = text.lower().find(marker.lower())
    if marker_position < 0:
        return None

    payload = text[marker_position + len(marker):].lstrip()
    try:
        value, _ = json.JSONDecoder().raw_decode(payload)
        return value
    except json.JSONDecodeError:
        return None


def _json_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def native_video_metadata(tags: dict[str, str]) -> dict[str, Any]:
    """Convert our FFmpeg-ready tags to values accepted by native VIDEO.

    The native component encoder JSON-serializes every metadata value itself.
    ``parameters`` is deliberately omitted here because it is an A1111 text
    field and must be written as a raw container tag by the lossless remux
    performed after the native encoder finishes.
    """
    native: dict[str, Any] = {}
    for key, value in tags.items():
        if key == "parameters":
            continue
        try:
            native[key] = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            native[key] = value
    return native


def build_video_metadata(
    metadata: Any | None,
    prompt: dict[str, Any] | None,
    extra_pnginfo: dict[str, Any] | None,
) -> dict[str, str]:
    """Build the tags consumed by Civitai's proposed video metadata parser.

    ``parameters`` remains the A1111-compatible source of positive/negative
    prompts, settings, hashes, and Civitai resources. Structured tags preserve
    the ComfyUI prompt/workflow and make the resource list available without
    parsing the human-readable parameters string.
    """
    tags: dict[str, str] = {}

    parameters = getattr(metadata, "a111_params", "") if metadata is not None else ""
    if parameters:
        tags["parameters"] = parameters

    if prompt is not None:
        tags["prompt"] = _json_value(prompt)

    extra = dict(extra_pnginfo or {})
    for key, value in extra.items():
        tags[str(key)] = _json_value(value)

    resources = extract_json_after(parameters, "Civitai resources:")
    if resources is not None:
        serialized_resources = _json_value(resources)
        tags["civitaiResources"] = serialized_resources

        # Keep this under the proposed generic metadata key too. This gives
        # future readers a lossless structured fallback while parameters keeps
        # compatibility with existing A1111/Civitai processors.
        extra_metadata = None
        if "extraMetadata" in tags:
            try:
                extra_metadata = json.loads(tags["extraMetadata"])
            except json.JSONDecodeError:
                pass
        if isinstance(extra_metadata, dict):
            extra_metadata.setdefault("civitaiResources", resources)
            tags["extraMetadata"] = _json_value(extra_metadata)
        elif "extraMetadata" not in tags:
            tags["extraMetadata"] = _json_value({"civitaiResources": resources})

    for key, value in list(tags.items()):
        if len(value.encode("utf-8")) > MAX_METADATA_VALUE_BYTES:
            raise ValueError(f"Video metadata field '{key}' exceeds the 2 MiB safety limit.")

    return tags


def escape_ffmetadata(value: str) -> str:
    """Escape a value for FFmpeg's FFMETADATA1 format."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace("#", "\\#")
        .replace("=", "\\=")
        .replace("\n", "\\\n")
    )


def write_ffmetadata(path: str | os.PathLike[str], tags: dict[str, str]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as metadata_file:
        metadata_file.write(";FFMETADATA1\n")
        for key, value in tags.items():
            metadata_file.write(f"{escape_ffmetadata(key)}={escape_ffmetadata(value)}\n")


def find_ffmpeg() -> str:
    forced_path = os.environ.get("VHS_FORCE_FFMPEG_PATH") or os.environ.get("IMAGE_SAVER_FFMPEG_PATH")
    if forced_path and os.path.isfile(forced_path):
        return forced_path

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        return get_ffmpeg_exe()
    except Exception as error:
        raise RuntimeError(
            "Image Saver Video Metadata requires FFmpeg. Install FFmpeg or set "
            "IMAGE_SAVER_FFMPEG_PATH to its executable."
        ) from error


def _output_path(source: Path, suffix: str, overwrite: bool) -> Path:
    if overwrite:
        return source

    suffix = suffix or "_civitai"
    candidate = source.with_name(f"{source.stem}{suffix}{source.suffix}")
    counter = 1
    while candidate.exists():
        candidate = source.with_name(f"{source.stem}{suffix}_{counter}{source.suffix}")
        counter += 1
    return candidate


def embed_video_metadata(
    source: str | os.PathLike[str],
    tags: dict[str, str],
    suffix: str = "_civitai",
    overwrite: bool = False,
) -> str:
    """Copy a video while adding container metadata, preserving all streams."""
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(f"Video file does not exist: {source_path}")

    extension = source_path.suffix.lower()
    if extension not in {".mp4", ".webm"}:
        raise ValueError(f"Only MP4 and WebM videos are supported, got '{source_path.suffix}'.")

    output_path = _output_path(source_path, suffix, overwrite)
    temporary_output: Path | None = None
    if overwrite:
        temporary_file = tempfile.NamedTemporaryFile(
            prefix=f"{source_path.stem}_",
            suffix=source_path.suffix,
            dir=source_path.parent,
            delete=False,
        )
        temporary_file.close()
        temporary_output = Path(temporary_file.name)
        ffmpeg_output = temporary_output
    else:
        ffmpeg_output = output_path

    metadata_file = tempfile.NamedTemporaryFile(
        prefix="image_saver_video_metadata_",
        suffix=".txt",
        mode="w",
        encoding="utf-8",
        newline="\n",
        delete=False,
    )
    metadata_file.close()

    try:
        write_ffmetadata(metadata_file.name, tags)
        command = [
            find_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
            "-f",
            "ffmetadata",
            "-i",
            metadata_file.name,
            "-map",
            "0",
            "-map_metadata",
            "1",
            "-c",
            "copy",
        ]
        if extension == ".mp4":
            command.extend(["-movflags", "use_metadata_tags+faststart"])
        command.append(str(ffmpeg_output))
        subprocess.run(command, check=True, capture_output=True, text=True)

        if overwrite and temporary_output is not None:
            os.replace(temporary_output, source_path)
        return str(output_path)
    except subprocess.CalledProcessError as error:
        details = (error.stderr or error.stdout or "").strip()
        raise RuntimeError(f"FFmpeg could not write video metadata: {details}") from error
    finally:
        try:
            os.remove(metadata_file.name)
        except FileNotFoundError:
            pass
        if temporary_output is not None and temporary_output.exists():
            temporary_output.unlink()


def unpack_vhs_filenames(value: Any) -> tuple[bool, list[str]]:
    """Accept the tuple returned by VideoHelperSuite's VHS_FILENAMES type."""
    if isinstance(value, tuple) and len(value) == 2:
        save_output, files = value
        if isinstance(files, (list, tuple)):
            return bool(save_output), [os.fspath(item) for item in files]
    if isinstance(value, (list, tuple)):
        return True, [os.fspath(item) for item in value]
    raise TypeError("Expected the VHS_FILENAMES value returned by VideoHelperSuite.")


def pack_vhs_filenames(save_output: bool, files: Iterable[str]) -> tuple[bool, list[str]]:
    return bool(save_output), list(files)
