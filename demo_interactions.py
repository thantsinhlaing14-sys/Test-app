import csv
import time
import wave
import winsound
from array import array
from pathlib import Path
from bridge import get_output_mode, reset_display, send_event, send_text
from servo_controller import close_mouth, play_speech

AUDIO_DIR = Path(__file__).resolve().parent / "static" / "audio"
TEXTS_CSV = Path(__file__).resolve().parent / "texts.csv"
TEXT_CHUNK_DELAY_SECONDS = 0.18
AUDIO_LEAD_MS = 200

def _load_texts():
    texts = {}
    if not TEXTS_CSV.exists():
        return texts
    with open(TEXTS_CSV, "r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            audio = (row.get("audio") or row.get("file") or row.get("filename") or "").strip()
            text = (row.get("text") or row.get("transcript") or "").strip()
            if audio:
                texts[audio] = text
    return texts

def _discover_interactions():
    texts = _load_texts()
    interactions = []
    for path in sorted(AUDIO_DIR.glob("*.wav")):
        name = path.stem
        interactions.append({
            "id": name,
            "label": name,
            "text": texts.get(path.name, ""),
            "audio": path.name,
        })
    return interactions

def get_interactions():
    return _discover_interactions()

def _read_wav(path):
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    if sample_width == 1:
        mono = [(sample - 128) / 128 for sample in frames]
    elif sample_width == 2:
        samples = array("h")
        samples.frombytes(frames)
        mono = [sample / 32768 for sample in samples]
    elif sample_width == 4:
        samples = array("i")
        samples.frombytes(frames)
        mono = [sample / 2147483648 for sample in samples]
    else:
        raise ValueError(f"unsupported WAV sample width: {sample_width}")

    if channels > 1:
        mono = [
            sum(mono[index:index + channels]) / channels
            for index in range(0, len(mono), channels)
        ]

    return mono, sample_rate

def _play_audio_file(filename):
    path = AUDIO_DIR / filename
    if not path.exists():
        send_text(f"\n\nAudio placeholder missing: {filename}")
        return

    audio, sample_rate = _read_wav(path)
    duration_seconds = len(audio) / sample_rate if sample_rate else 0

    if get_output_mode() == "phone":
        send_event("audio", {"src": f"/static/audio/{filename}"})
    else:
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)

    time.sleep(AUDIO_LEAD_MS / 1000)
    play_speech(audio, sample_rate)
    time.sleep(max(0, duration_seconds - (AUDIO_LEAD_MS / 1000)))
    if get_output_mode() == "phone":
        send_event("audio-stop", None)
    else:
        winsound.PlaySound(None, winsound.SND_PURGE)
    close_mouth()

def _stream_text(text):
    for sentence in text.split(". "):
        clean = sentence.strip()
        if not clean:
            continue
        suffix = "" if clean.endswith((".", "!", "?")) else "."
        send_text(clean + suffix + " ")
        time.sleep(TEXT_CHUNK_DELAY_SECONDS)

def run_interaction(interaction):
    reset_display()
    send_event("interaction", {"id": interaction["id"], "label": interaction["label"]})
    _stream_text(interaction["text"])
    _play_audio_file(interaction["audio"])
    send_event("done")
