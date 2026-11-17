"""§13 items 9 and 17: exports."""
from __future__ import annotations

import io
import subprocess
import zipfile
from urllib.parse import quote

import numpy as np
import pytest
import soundfile as sf
from api_helpers import make_song

from app import exporting
from app.audio import ffprobe_bin

EXPECTED_SUBTYPE = {"wav": "PCM_24", "flac": "PCM_24"}


def _read(content: bytes):
    data, sr = sf.read(io.BytesIO(content), dtype="float32", always_2d=True)
    return data, sr


def _no_tmp_left(paths):
    return list((paths.tmp / "api").iterdir()) == []


@pytest.mark.parametrize("fmt", ["wav", "flac", "mp3"])
def test_export_stem_formats(client, paths, fmt):
    sid = make_song(artist="AC/DC", title="Back: In?")
    r = client.get(f"/api/songs/{sid}/export/stem/vocals", params={"format": fmt})
    assert r.status_code == 200, r.text
    expected = f"AC_DC - Back_ In_ [vocals].{fmt}"
    cd = r.headers["content-disposition"]
    assert f'filename="{expected}"' in cd
    assert f"filename*=UTF-8''{quote(expected, safe='')}" in cd
    info = sf.info(io.BytesIO(r.content))
    assert info.samplerate == 44100 and info.channels == 2
    if fmt in EXPECTED_SUBTYPE:
        assert info.subtype == EXPECTED_SUBTYPE[fmt]
        assert info.format == fmt.upper()
    else:
        assert info.format in ("MP3", "MPEG")
        out = paths.root / "probe.mp3"
        out.write_bytes(r.content)
        probe = subprocess.run(
            [ffprobe_bin(), "-v", "error", "-show_entries",
             "stream=bit_rate", "-of", "csv=p=0", str(out)], capture_output=True, text=True,
        ).stdout.strip()
        assert probe == "320000"
    assert _no_tmp_left(paths)


def test_export_stem_default_format_and_errors(client):
    sid = make_song(title="Só")
    r = client.get(f"/api/songs/{sid}/export/stem/drums")
    assert r.status_code == 200 and sf.info(io.BytesIO(r.content)).format == "WAV"
    assert "filename*=UTF-8''S%C3%B3%20%5Bdrums%5D.wav" in r.headers["content-disposition"]
    assert 'filename="So [drums].wav"' in r.headers["content-disposition"]
    r = client.get(f"/api/songs/{sid}/export/stem/vocals", params={"format": "ogg"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get(f"/api/songs/{sid}/export/stem/piano", params={"format": "wav"}).status_code == 404


@pytest.mark.parametrize("fmt", ["flac", "mp3"])
def test_export_zip(client, paths, fmt):
    sid = make_song(stem_mode=6, title="T")
    r = client.get(f"/api/songs/{sid}/export/zip", params={"format": fmt})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert 'filename="T [stems].zip"' in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert names == [f"{s}.{fmt}" for s in ("vocals", "drums", "bass", "guitar", "piano", "other")]
    info = sf.info(io.BytesIO(zf.read(names[0])))
    assert info.samplerate == 44100 and info.channels == 2
    assert client.get(f"/api/songs/{sid}/export/zip", params={"format": "aac"}).status_code == 422
    assert _no_tmp_left(paths)


def test_mix_gains_applied(client):
    sid = make_song(duration=2.0, amplitude=0.25)
    r = client.post(f"/api/songs/{sid}/export/mix", json={"gains": {"vocals": 1.0}, "format": "wav"})
    assert r.status_code == 200, r.text
    assert "[mix].wav" in r.headers["content-disposition"]
    data, sr = _read(r.content)
    assert sr == 44100 and data.shape == (88200, 2)
    assert abs(float(np.max(np.abs(data))) - 0.25) < 0.01

    r = client.post(f"/api/songs/{sid}/export/mix", json={"gains": {"vocals": 0.5, "bass": 0.0}, "format": "wav"})
    assert abs(float(np.max(np.abs(_read(r.content)[0]))) - 0.125) < 0.01

    # vocals (440 Hz) at gain 1 + bass (55 Hz) at 0.5: check spectral magnitudes
    r = client.post(f"/api/songs/{sid}/export/mix", json={"gains": {"vocals": 1.0, "bass": 0.5}, "format": "flac"})
    mono = _read(r.content)[0][:, 0]
    spec = np.abs(np.fft.rfft(mono)) / len(mono) * 2
    freqs = np.fft.rfftfreq(len(mono), 1 / 44100)
    at = lambda f: spec[np.argmin(np.abs(freqs - f))]  # noqa: E731
    assert abs(at(440) - 0.25) < 0.01 and abs(at(55) - 0.125) < 0.01 and at(110) < 0.01


def test_mix_peak_normalized(client):
    sid = make_song(duration=2.0, amplitude=0.9)
    gains = {s: 1.0 for s in ("vocals", "drums", "bass", "other")}
    r = client.post(f"/api/songs/{sid}/export/mix", json={"gains": gains, "format": "wav"})
    peak = float(np.max(np.abs(_read(r.content)[0])))
    assert 0.97 < peak <= 0.981


def test_mix_crop_and_speed(client):
    sid = make_song(duration=3.0)
    r = client.post(f"/api/songs/{sid}/export/mix",
                    json={"gains": {"vocals": 1}, "start_s": 1.0, "end_s": 2.0, "format": "wav"})
    assert _read(r.content)[0].shape[0] == 44100

    r = client.post(f"/api/songs/{sid}/export/mix",
                    json={"gains": {"vocals": 1}, "speed": 0.5, "semitones": 0, "format": "wav"})
    n = _read(r.content)[0].shape[0]
    assert abs(n - 2 * 3 * 44100) <= 0.01 * 2 * 3 * 44100

    r = client.post(f"/api/songs/{sid}/export/mix",
                    json={"gains": {"vocals": 1}, "speed": 1.0, "semitones": 12, "format": "wav"})
    mono = _read(r.content)[0][20000:100000, 0]
    freqs = np.fft.rfftfreq(len(mono), 1 / 44100)
    assert abs(freqs[np.argmax(np.abs(np.fft.rfft(mono)))] - 880) < 10


@pytest.mark.parametrize(
    "body",
    [
        {"gains": {"piano": 1.0}},
        {"gains": {"vocals": 1.5}},
        {"gains": {"vocals": 0, "drums": 0}},
        {"gains": {}},
        {"gains": {"vocals": 1}, "speed": 0.4},
        {"gains": {"vocals": 1}, "speed": 1.6},
        {"gains": {"vocals": 1}, "semitones": 13},
        {"gains": {"vocals": 1}, "start_s": 2.0, "end_s": 1.0},
        {"gains": {"vocals": 1}, "start_s": 1.0, "end_s": 1.4},
        {"gains": {"vocals": 1}, "end_s": 3.5},
        {"gains": {"vocals": 1}, "start_s": -1},
        {"gains": {"vocals": 1}, "format": "ogg"},
        {"gains": "all"},
    ],
)
def test_mix_validation(client, body):
    sid = make_song(duration=3.0)
    r = client.post(f"/api/songs/{sid}/export/mix", json={"format": "wav", **body})
    assert r.status_code == 422, body
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_filename_helpers():
    assert exporting.export_filename("AC/DC", "Back: In?", "vocals", "mp3") == "AC_DC - Back_ In_ [vocals].mp3"
    assert exporting.export_filename(None, 'a"b<c>d|e*f\\g', "mix", "wav") == "a_b_c_d_e_f_g [mix].wav"
