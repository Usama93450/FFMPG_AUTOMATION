#!/usr/bin/env python3
"""
demo_ffmpeg_pipeline.py
Pipeline:
 - Finds nearest keyframes with ffprobe
 - Keyframe-safe trimming
 - Scales/pads to 1080x1920
 - Normalizes audio (loudnorm)
 - Burns SRT captions (optional)
"""

import argparse
import json
import os
import subprocess
from typing import List, Optional


def fix_path_for_ffmpeg(path: str) -> str:
    """
    Convert to absolute path with forward slashes for FFmpeg.
    For subtitles filter, escape colon after drive letter.
    """
    abs_path = os.path.abspath(path).replace("\\", "/")
    if ":" in abs_path[1:3]:  # Example: D:/something
        abs_path = abs_path.replace(":", "\\:", 1)
    return abs_path


def run_cmd(cmd: List[str]):
    """Run subprocess and stream FFmpeg output live."""
    print("\n[CMD]", " ".join(cmd), "\n")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        print(line, end="")  # Live output
    process.wait()
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, cmd)


def get_keyframe_times(input_path: str) -> List[float]:
    """Return sorted keyframe timestamps from ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-select_streams", "v",
        "-show_entries", "frame=pkt_pts_time,key_frame",
        "-of", "json",
        os.path.abspath(input_path).replace("\\", "/")
    ]
    out = subprocess.check_output(cmd)
    frames = json.loads(out).get("frames", [])
    return sorted(
        float(f["pkt_pts_time"])
        for f in frames
        if int(f["key_frame"]) == 1 and "pkt_pts_time" in f
    )


def find_keyframe_before_or_equal(times: List[float], t: float) -> float:
    """Nearest keyframe <= t."""
    return max((kf for kf in times if kf <= t), default=0.0)


def find_keyframe_after_or_equal(times: List[float], t: float) -> float:
    """Nearest keyframe >= t."""
    return min((kf for kf in times if kf >= t), default=times[-1] if times else t)


def build_ffmpeg_command(
    input_path: str,
    srt_path: Optional[str],
    start_kf: float,
    duration: float,
    output_path: str,
    crf: int = 18,
    preset: str = "veryfast"
) -> List[str]:
    """Build FFmpeg pipeline command."""
    scale_pad = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )

    if srt_path:
        srt_fixed = fix_path_for_ffmpeg(srt_path)
        subtitles = (
            f"subtitles='{srt_fixed}':"
            f"force_style='Fontsize=36,PrimaryColour=&HFFFFFF&'"
        )
        vf = f"{scale_pad},{subtitles}"
    else:
        vf = scale_pad

    return [
        "ffmpeg", "-y",
        "-ss", f"{start_kf:.3f}",
        "-i", os.path.abspath(input_path).replace("\\", "/"),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-r", "30",
        "-c:a", "aac",
        "-b:a", "192k",
        os.path.abspath(output_path).replace("\\", "/")
    ]


def main():
    parser = argparse.ArgumentParser(description="FFmpeg pipeline with keyframe trimming and optional subtitles.")
    parser.add_argument("--input", "-i", required=True, help="Input video file")
    parser.add_argument("--start", type=float, required=True, help="Start time (seconds)")
    parser.add_argument("--end", type=float, required=True, help="End time (seconds)")
    parser.add_argument("--srt", type=str, help="Optional subtitles SRT file")
    parser.add_argument("--output", "-o", default="output_demo.mp4", help="Output video filename")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        raise SystemExit(f"❌ Input file not found: {args.input}")
    if args.srt and not os.path.isfile(args.srt):
        raise SystemExit(f"❌ SRT file not found: {args.srt}")

    print("🔍 Scanning keyframes...")
    keyframes = get_keyframe_times(args.input)

    if keyframes:
        start_kf = find_keyframe_before_or_equal(keyframes, args.start)
        end_kf = find_keyframe_after_or_equal(keyframes, args.end)
        if end_kf <= start_kf:
            end_kf = max(args.end, start_kf + 0.1)
    else:
        print("⚠ No keyframes found — using exact times.")
        start_kf, end_kf = args.start, args.end

    duration = max(0.1, end_kf - start_kf)
    print(f"🎯 Requested: {args.start:.3f}s → {args.end:.3f}s")
    print(f"🎯 Keyframe-aligned: {start_kf:.3f}s → {end_kf:.3f}s (Duration: {duration:.3f}s)")

    cmd = build_ffmpeg_command(args.input, args.srt, start_kf, duration, args.output)

    try:
        run_cmd(cmd)
        print(f"✅ Done! Output saved to: {args.output}")
    except subprocess.CalledProcessError:
        print("❌ FFmpeg failed — check the command above for errors.")


if __name__ == "__main__":
    main()
