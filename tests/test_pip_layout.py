from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

compose_pip = importlib.import_module("compose_pip")
generate_offset_review_clips = importlib.import_module("generate_offset_review_clips")
pip_layout = importlib.import_module("pip_layout")
render_final_video = importlib.import_module("render_final_video")


class PipLayoutTests(unittest.TestCase):
    def test_render_final_video_accepts_new_layout_name(self) -> None:
        filter_complex = render_final_video.build_filter_complex(
            video_layout="pip_top_right",
            scale_ratio=0.25,
            margin=48,
            audio_mode="mix",
            base_video_filter=None,
            overlay_video_filter=None,
            base_audio_filter=None,
            overlay_audio_filter=None,
        )

        self.assertIn("scale=iw*0.25:ih*0.25", filter_complex)
        self.assertIn("overlay=x=W-w-48:y=48", filter_complex)

    def test_render_final_video_keeps_legacy_layout_alias(self) -> None:
        filter_complex = render_final_video.build_filter_complex(
            video_layout="pip_top_right_30",
            scale_ratio=0.25,
            margin=48,
            audio_mode="mix",
            base_video_filter=None,
            overlay_video_filter=None,
            base_audio_filter=None,
            overlay_audio_filter=None,
        )

        self.assertIn("scale=iw*0.25:ih*0.25", filter_complex)

    def test_review_clip_layout_keeps_legacy_layout_alias(self) -> None:
        filter_complex = generate_offset_review_clips.build_filter_complex(
            video_layout="pip_top_right_30",
            scale_ratio=0.25,
            margin=48,
            offset_frames=12,
            label="candidate_plus_12f",
            audio_mode="mix",
        )

        self.assertIn("scale=iw*0.25:ih*0.25", filter_complex)

    def test_compose_pip_uses_requested_scale_ratio(self) -> None:
        filter_complex = compose_pip.build_filter_complex(
            scale_ratio=0.25,
            margin=48,
            audio_mode="mix",
        )

        self.assertIn("scale=iw*0.25:ih*0.25", filter_complex)

    def test_default_pip_scale_percent_is_25(self) -> None:
        self.assertEqual(pip_layout.resolve_scale_ratio(None), 0.25)


if __name__ == "__main__":
    unittest.main()
