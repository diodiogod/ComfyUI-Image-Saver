import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from .video import (
    build_video_metadata,
    embed_video_metadata,
    escape_ffmetadata,
    native_video_metadata,
    select_vhs_video_file,
    unpack_vhs_filenames,
)


def test_build_video_metadata_preserves_civitai_contract():
    metadata = SimpleNamespace(
        a111_params=(
            "positive\nNegative prompt: negative\n"
            "Steps: 12, Hashes: {\"model\":\"ABCDEF1234\"}, "
            "Civitai resources: [{\"modelVersionId\":123,\"type\":\"checkpoint\"}]"
        )
    )
    tags = build_video_metadata(
        metadata,
        {"1": {"class_type": "KSampler"}},
        {"workflow": {"nodes": []}},
    )

    assert tags["parameters"] == metadata.a111_params
    assert json.loads(tags["prompt"])["1"]["class_type"] == "KSampler"
    assert json.loads(tags["workflow"]) == {"nodes": []}
    assert json.loads(tags["civitaiResources"])[0]["modelVersionId"] == 123
    assert json.loads(tags["extraMetadata"])["civitaiResources"][0]["type"] == "checkpoint"


def test_escape_ffmetadata():
    assert escape_ffmetadata(r"a=b;c#d\e\nf") == r"a\=b\;c\#d\\e\\nf"


def test_unpack_vhs_filenames():
    assert unpack_vhs_filenames((False, ["one.mp4", "two.webm"])) == (False, ["one.mp4", "two.webm"])
    assert unpack_vhs_filenames(["one.mp4"]) == (True, ["one.mp4"])


def test_select_vhs_video_file_ignores_metadata_png():
    files = ["AnimateDiff_00001.png", "AnimateDiff_00001.mp4"]
    assert select_vhs_video_file(files) == "AnimateDiff_00001.mp4"


def test_select_vhs_video_file_prefers_audio_muxed_output():
    files = [
        "AnimateDiff_00001.png",
        "AnimateDiff_00001.mp4",
        "AnimateDiff_00001-audio.mp4",
    ]
    assert select_vhs_video_file(files) == "AnimateDiff_00001-audio.mp4"


def test_select_vhs_video_file_rejects_image_formats_clearly():
    with pytest.raises(ValueError, match="no MP4 or WebM"):
        select_vhs_video_file(["AnimateDiff_00001.png", "AnimateDiff_00001.gif"])


def test_native_video_metadata_avoids_double_serializing_parameters():
    tags = {
        "parameters": "positive\nNegative prompt: negative",
        "prompt": '{"1":{"class_type":"KSampler"}}',
        "civitaiResources": '[{"modelVersionId":123}]',
    }

    native = native_video_metadata(tags)

    assert "parameters" not in native
    assert native["prompt"] == {"1": {"class_type": "KSampler"}}
    assert native["civitaiResources"] == [{"modelVersionId": 123}]


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="FFmpeg and FFprobe are required")
def test_embed_video_metadata_mp4(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            shutil.which("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=16x16:d=0.1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )

    output = embed_video_metadata(
        source,
        {
            "parameters": "positive\nNegative prompt: negative",
            "civitaiResources": '[{"modelVersionId":123}]',
        },
    )
    probe = subprocess.run(
        [
            shutil.which("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format_tags=parameters,civitaiResources",
            "-of",
            "json",
            output,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    tags = json.loads(probe.stdout)["format"]["tags"]
    assert tags["parameters"] == "positive\nNegative prompt: negative"
    assert json.loads(tags["civitaiResources"])[0]["modelVersionId"] == 123
