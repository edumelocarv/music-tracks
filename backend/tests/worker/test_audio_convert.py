"""Regression: ffmpeg writing lots of stderr must not deadlock convert_to_wav."""
import subprocess
import threading

import numpy as np
import soundfile as sf

from app.audio import convert_to_wav, ffmpeg_bin


def test_convert_damaged_mp3_does_not_hang(tmp_path):
    wav = tmp_path / "src.wav"
    sr = 44100
    t = np.arange(sr * 240) / sr
    sf.write(wav, (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), sr)
    mp3 = tmp_path / "src.mp3"
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(wav), str(mp3)], check=True)
    data = bytearray(mp3.read_bytes())
    rng = np.random.default_rng(0)
    for pos in rng.integers(2000, len(data) - 10, size=40000):
        data[int(pos)] = int(rng.integers(0, 256))
    mp3.write_bytes(bytes(data))

    out = tmp_path / "out.wav"
    errors: list[BaseException] = []

    def run():
        try:
            convert_to_wav(mp3, out, duration_hint=240.0, on_progress=lambda f: None)
        except BaseException as exc:  # noqa: BLE001 — failure is acceptable, hanging is not
            errors.append(exc)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout=60)
    assert not th.is_alive(), "convert_to_wav hung on a damaged file"
