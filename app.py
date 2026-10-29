import os
import re
import uuid
import shutil
import subprocess
import threading
from pathlib import Path

from flask import Flask, render_template, request, send_from_directory, flash, redirect, url_for
from PIL import Image, ImageDraw, ImageFont, ImageOps
import imageio_ffmpeg

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "local-property-video-generator")
app.config["MAX_CONTENT_LENGTH"] = 120 * 1024 * 1024
ALLOWED = {".jpg", ".jpeg", ".png", ".webp"}
MIN_IMAGES = 4
MAX_IMAGES = 8

# Loaded only once per server process. First run downloads the model (internet required).
_captioner = None
_captioner_lock = threading.Lock()


def get_captioner():
    global _captioner
    with _captioner_lock:
        if _captioner is not None:
            return _captioner
        try:
            from transformers import pipeline
            _captioner = pipeline(
                "image-to-text",
                model="Salesforce/blip-image-captioning-base",
                device=-1
            )
            return _captioner
        except Exception as exc:
            raise RuntimeError(
                "AI photo analysis could not start. Check internet on first run and "
                "confirm setup completed. Details: " + str(exc)
            )


def analyze_photo(path):
    """Analyze one photo and return a useful, room-specific caption."""
    captioner = get_captioner()
    result = captioner(str(path), max_new_tokens=48)
    raw = (result[0].get("generated_text", "") if result else "").strip()
    raw = re.sub(r"\s+", " ", raw).strip().rstrip(". ")
    lower = raw.lower()

    rules = [
        ("living room", ["sofa", "couch", "television", " tv", "living room", "coffee table", "armchair"]),
        ("bedroom", ["bed", "bedroom", "pillow", "mattress", "nightstand"]),
        ("kitchen", ["kitchen", "oven", "stove", "refrigerator", "cabinet", "countertop", "sink"]),
        ("bathroom", ["bathroom", "shower", "bathtub", "toilet", "washbasin"]),
        ("balcony", ["balcony", "terrace", "railing", "outdoor view"]),
        ("dining area", ["dining table", "dining room", "dining chairs"]),
        ("exterior", ["house exterior", "building exterior", "front of a house", "outside a house", "building"]),
        ("garden", ["garden", "lawn", "plants", "yard"]),
    ]
    room = "Property space"
    for label, terms in rules:
        if any(term in lower for term in terms):
            room = label.title()
            break

    generic_phrases = (
        "design ideas", "interior design", "design inspiration", "room design",
        "home design", "ideas for", "a photo of", "an image of", "a picture of"
    )
    is_generic = (not raw) or any(p in lower for p in generic_phrases) or len(raw.split()) < 3
    if is_generic:
        defaults = {
            "Living Room": "A living area with comfortable sofa seating and a coffee table.",
            "Bedroom": "A comfortable bedroom arranged for rest and privacy.",
            "Kitchen": "A practical kitchen with visible work surfaces and storage.",
            "Bathroom": "A washroom with its visible bathroom fixtures.",
            "Balcony": "A balcony that adds an outdoor space to the home.",
            "Dining Area": "A dining area arranged for everyday meals.",
            "Exterior": "A view of the property's exterior and entrance.",
            "Garden": "An outdoor area with greenery.",
            "Property Space": "A look at the property's interior and visible finishes.",
        }
        caption = defaults.get(room, defaults["Property Space"])
    else:
        caption = raw[0].upper() + raw[1:] + ("." if not raw.endswith(".") else "")
    return room, caption



def normalize_room_label(label):
    """Normalize a user-provided room label; never guess the room from an unreliable caption."""
    raw = re.sub(r"\s+", " ", (label or "").strip().lower())
    aliases = {
        "balcony": "Balcony", "terrace": "Balcony",
        "outside": "Exterior", "outdoor": "Exterior", "exterior": "Exterior", "front": "Exterior",
        "kitchen": "Kitchen", "bedroom": "Bedroom", "bedroom 1": "Bedroom", "bedroom 2": "Bedroom",
        "living room": "Living Room", "living area": "Living Room", "lounge": "Living Room",
        "bathroom": "Bathroom", "washroom": "Bathroom", "toilet": "Bathroom",
        "dining room": "Dining Area", "dining area": "Dining Area",
        "garden": "Garden", "yard": "Garden", "parking": "Parking",
        "property": "Property", "other": "Property"
    }
    return aliases.get(raw, "Property")


def room_caption(room):
    """Use concise factual phrasing tied to the selected room label."""
    captions = {
        "Balcony": "A balcony offering an outdoor space to enjoy fresh air.",
        "Exterior": "A view of the property's exterior and outdoor surroundings.",
        "Kitchen": "A practical kitchen space with its visible fixtures and work surfaces.",
        "Bedroom": "A comfortable bedroom designed for rest and privacy.",
        "Living Room": "A living area arranged for relaxing and spending time together.",
        "Bathroom": "A bathroom with its visible fittings and fixtures.",
        "Dining Area": "A dining area for everyday meals and family gatherings.",
        "Garden": "An outdoor green space beside the property.",
        "Parking": "The property's parking area.",
        "Property": "A look at another part of the property."
    }
    return captions.get(room, captions["Property"])

def clean_property_facts(text):
    """Remove generic/malformed phrases and duplicate facts from property highlights."""
    text = re.sub(r"(?i)property highlights include|property highlights|key selling points|key highlights", "", text or "")
    text = re.sub(r"(?i)\b(?:living room|bedroom) design ideas\b", "", text)
    chunks = re.split(r"[,;\n]+", text)
    cleaned = []
    seen = set()
    skip_phrases = (
        "design ideas", "luxury apartment", "the grove", "key selling points",
        "property highlights", "three living room", "living room design"
    )
    for chunk in chunks:
        item = re.sub(r"\s+", " ", chunk).strip(" .-:;")
        low = item.lower()
        if not item or any(p in low for p in skip_phrases):
            continue
        if low in {"bedroom", "living room", "kitchen", "bathroom", "washroom", "highlights"}:
            continue
        key = re.sub(r"[^a-z0-9]", "", low)
        if key and key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned

def font(size, bold=False):
    candidates = []
    if os.name == "nt":
        candidates += [
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        ]
    candidates += ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for item in candidates:
        try:
            return ImageFont.truetype(item, size)
        except Exception:
            pass
    return ImageFont.load_default()


def wrap_text(draw, text, fnt, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = (current + " " + word).strip()
        if draw.textbbox((0, 0), trial, font=fnt)[2] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def make_poster(source_path, dest_path, room, caption, property_name, location, price, facts, scene_no, total, phone, property_type, bedrooms, area, bathrooms=""):
    # Portrait 720x1280 marketing frame, with a blurred/darkened photo background and clear text overlays.
    W, H = 720, 1280
    src = Image.open(source_path).convert("RGB")
    photo = ImageOps.fit(src, (W, 900), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    # Slightly soften and darken photo for premium ad look.
    from PIL import ImageEnhance, ImageFilter
    photo = ImageEnhance.Color(photo).enhance(1.08)
    canvas = Image.new("RGB", (W, H), (12, 19, 29))
    canvas.paste(photo, (0, 0))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    # Photo gradient tint.
    for y in range(650, 900):
        alpha = int(145 * (y - 650) / 250)
        od.rectangle((0, y, W, y + 1), fill=(5, 10, 18, alpha))
    od.rectangle((0, 0, W, 95), fill=(8, 14, 24, 150))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay)
    d = ImageDraw.Draw(canvas)
    white = (255, 255, 255, 255)
    gold = (239, 190, 105, 255)
    muted = (207, 216, 226, 255)

    d.rounded_rectangle((34, 30, 290, 76), radius=20, fill=(239, 190, 105, 245))
    d.text((52, 41), f"PROPERTY TOUR  •  {scene_no:02d}/{total:02d}", font=font(18, True), fill=(18, 24, 33, 255))
    # A compact editorial headline gives each frame a designed ad layout, not just a photo slideshow.
    if scene_no == 1:
        d.text((34, 112), "FIND YOUR NEXT HOME", font=font(22, True), fill=white)
        d.text((34, 145), f"{property_type.upper()}  •  {price.strip()}", font=font(18, True), fill=gold)
    else:
        d.text((34, 112), room.upper(), font=font(24, True), fill=white)
    # Bottom information area
    d.rounded_rectangle((24, 815, W-24, H-24), radius=28, fill=(10, 17, 27, 248))
    d.text((54, 850), room.upper(), font=font(20, True), fill=gold)
    title = property_name.strip() or "Premium Property"
    title_lines = wrap_text(d, title, font(36, True), W-108)[:2]
    y = 890
    for line in title_lines:
        d.text((54, y), line, font=font(36, True), fill=white)
        y += 44
    if scene_no == 1:
        d.text((54, y+3), f"{location.strip()}  |  {price.strip()}", font=font(20, True), fill=gold)
        y += 44
        specs = "  •  ".join(x for x in [f"{bedrooms} bedrooms" if bedrooms else "", f"{bathrooms} bathrooms" if bathrooms else "", area] if x)
        if specs:
            for line in wrap_text(d, specs, font(17, True), W-108)[:1]:
                d.text((54, y), line, font=font(17, True), fill=white)
            y += 28
    desc_lines = wrap_text(d, caption, font(21), W-108)[:4]
    for line in desc_lines:
        d.text((54, y), line, font=font(21), fill=muted)
        y += 31
    if scene_no == total:
        d.rounded_rectangle((44, H-132, W-44, H-78), radius=16, fill=(239, 190, 105, 245))
        contact_line = f"CONTACT: {phone.strip()}"
        d.text((60, H-117), contact_line[:48], font=font(19, True), fill=(18, 24, 33, 255))
        d.text((54, H-62), "BOOK YOUR SITE VISIT TODAY", font=font(17, True), fill=gold)
    canvas.convert("RGB").save(dest_path, quality=94)


def speak_to_wav(text, out_path):
    """Create narration with Windows built-in Speech API (avoids pyttsx3 COM errors)."""
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise RuntimeError("Windows PowerShell was not found; voice-over requires Windows Speech support.")
    text_file = out_path.with_suffix(".txt")
    script_file = out_path.with_suffix(".ps1")
    text_file.write_text(text, encoding="utf-8")
    script = r"""
param([string]$TextPath, [string]$OutputPath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.Volume = 100
    $synth.Rate = 1
    $synth.SetOutputToWaveFile($OutputPath)
    $narration = Get-Content -LiteralPath $TextPath -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($narration)) { throw 'Narration text is empty.' }
    $synth.Speak($narration)
    $synth.SetOutputToNull()
} finally {
    $synth.Dispose()
}
"""
    script_file.write_text(script, encoding="utf-8")
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(script_file), str(text_file), str(out_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180
        )
        if result.returncode != 0:
            raise RuntimeError("Windows voice-over failed: " + (result.stderr or result.stdout)[-900:])
        if not out_path.exists() or out_path.stat().st_size <= 1000:
            raise RuntimeError("Windows did not create a usable narration audio file.")
    finally:
        for temp_path in (text_file, script_file):
            try:
                temp_path.unlink()
            except OSError:
                pass


def make_scene_video(image_path, audio_path, out_path, duration):
    """Create one visual scene. Audio is added once to the final joined video."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    vf = (
        "scale=800:1422:force_original_aspect_ratio=increase,"
        "crop=800:1422,"
        "zoompan=z='min(zoom+0.0007,1.045)':d=1:s=720x1280:fps=24,"
        f"fade=t=in:st=0:d=0.28,fade=t=out:st={max(0, duration - 0.28):.3f}:d=0.28,"
        "setsar=1,format=yuv420p"
    )
    cmd = [
        ffmpeg, "-y", "-loop", "1", "-i", str(image_path),
        "-t", f"{duration:.3f}", "-vf", vf,
        "-an", "-r", "24", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
        "-pix_fmt", "yuv420p", str(out_path)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def build_ad_video(photo_paths, details, output_path):
    property_name = details["property_name"]
    location = details["location"]
    price = details["price"]
    facts = details["highlights"]
    phone = details["contact"]
    bathrooms = details.get("bathrooms", "")
    user_room_labels = [normalize_room_label(x) for x in details.get("photo_labels", [])]

    if not MIN_IMAGES <= len(photo_paths) <= MAX_IMAGES:
        raise RuntimeError("Please use 4–8 distinct property photos.")

    unique_photo_paths = []
    seen_photo_keys = set()
    for photo in photo_paths:
        try:
            key = (Path(photo).resolve().as_posix().lower(), Path(photo).stat().st_size)
        except Exception:
            key = str(photo).lower()
        if key not in seen_photo_keys:
            seen_photo_keys.add(key)
            unique_photo_paths.append(photo)
    photo_paths = unique_photo_paths
    total = len(photo_paths)
    if not MIN_IMAGES <= total <= MAX_IMAGES:
        raise RuntimeError("Please use 4–8 distinct property photos; duplicate selected files were removed.")

    # Give the opening and closing more time. For 4–8 photos this stays within 50 sec.
    base_durations = [8.0] + [5.5] * (total - 2) + [7.0]
    if sum(base_durations) < 30.0:
        extra_each = (30.0 - sum(base_durations)) / total
        base_durations = [d + extra_each for d in base_durations]

    work_dir = OUTPUT_DIR / ("work_" + uuid.uuid4().hex[:8])
    work_dir.mkdir(parents=True, exist_ok=True)
    scene_clips = []
    try:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        for idx, photo in enumerate(photo_paths, 1):
            if idx <= len(user_room_labels) and user_room_labels[idx - 1] != "Property":
                room = user_room_labels[idx - 1]
            else:
                room, _model_caption = analyze_photo(photo)
            short_caption = room_caption(room)
            low_facts = (facts or "").lower()
            sentences = []

            if idx == 1:
                prop_type = details.get("property_type", "property").strip().lower()
                article = "an" if prop_type[:1] in "aeiou" else "a"
                sentences.append(f"Welcome to {property_name}, {article} {prop_type} in {location}, priced at {price}.")
                specs = []
                if details.get("area"):
                    specs.append(f"{details['area']} of space")
                if details.get("bedrooms"):
                    specs.append(f"{details['bedrooms']} bedrooms")
                if bathrooms:
                    specs.append(f"{bathrooms} bathrooms")
                if specs:
                    sentences.append("It offers " + ", ".join(specs) + ".")
                # No filler such as "let's look at"; describe the visible first photo directly.
                if room == "Balcony":
                    sentences.append("The balcony adds a pleasant outdoor space to the home.")
                elif room == "Exterior":
                    sentences.append("The home has an inviting exterior and outdoor entrance.")
                elif room == "Parking":
                    sentences.append("Convenient parking is available at the property.")
                else:
                    sentences.append(short_caption.rstrip("."))
            else:
                # Keep every feature attached to the matching photo; do not narrate a detached highlight list.
                if room == "Bedroom":
                    if details.get("bedrooms"):
                        sentences.append(f"The home offers {details['bedrooms']} bedrooms, designed for comfort and privacy.")
                    else:
                        sentences.append("A comfortable bedroom with space to relax and unwind.")
                elif room == "Bathroom":
                    if bathrooms:
                        sentences.append(f"The property includes {bathrooms} bathrooms.")
                    else:
                        sentences.append("A clean, practical bathroom with its visible fixtures.")
                    if any(term in low_facts for term in ("attached bathroom", "attached washroom", "ensuite", "en-suite")):
                        sentences.append("The attached bathrooms add convenience and privacy.")
                elif room == "Kitchen":
                    if "modular" in low_facts:
                        sentences.append("The home features a modular kitchen with practical work and storage space.")
                    else:
                        sentences.append("The kitchen offers practical work surfaces and storage.")
                elif room == "Living Room":
                    if "spacious" in low_facts:
                        sentences.append("Enjoy a spacious living area for relaxing and spending time together.")
                    else:
                        sentences.append("The living area is a comfortable place to relax and spend time together.")
                elif room == "Balcony":
                    sentences.append("The balcony offers a little outdoor space to enjoy fresh air.")
                elif room == "Parking":
                    sentences.append("Convenient parking is available at the property.")
                    if any(term in low_facts for term in ("security", "24/7", "24x7")):
                        sentences.append("The property also offers the security features listed in its details.")
                elif room == "Exterior":
                    sentences.append("The exterior gives a view of the home's entrance and outdoor surroundings.")
                elif room in {"Garden", "Dining Area"}:
                    sentences.append(short_caption.rstrip("."))
                else:
                    sentences.append(short_caption.rstrip("."))

            if idx == total:
                sentences.append(f"For details or to arrange a viewing, contact us at {phone}. Book your site visit today.")

            scene_text = re.sub(r"\s+", " ", " ".join(sentences)).strip()
            audio = work_dir / f"scene_{idx:02d}.wav"
            speak_to_wav(scene_text, audio)
            import wave
            with wave.open(str(audio), "rb") as wf:
                speech_seconds = wf.getnframes() / float(wf.getframerate())

            # Use a little breathing room after speech. Keep the intro and CTA generous.
            duration = max(base_durations[idx - 1], speech_seconds / 1.08 + 0.35)
            # Overall cap: at most 50 seconds. Short scripts and concise sentences should fit.
            poster = work_dir / f"scene_{idx:02d}.jpg"
            silent_clip = work_dir / f"scene_{idx:02d}_silent.mp4"
            clip = work_dir / f"scene_{idx:02d}.mp4"
            make_poster(photo, poster, room, short_caption, property_name, location, price,
                        "", idx, total, phone, details.get("property_type", "Property"),
                        details.get("bedrooms", ""), details.get("area", ""), bathrooms)
            make_scene_video(poster, None, silent_clip, duration)

            # Fit only this scene's narration to this scene's image. Never speed the whole script up.
            tempo = max(1.0, min(1.12, speech_seconds / max(1.0, duration - 0.25)))
            audio_filter = f"atempo={tempo:.3f},apad,atrim=0:{duration:.3f},asetpts=PTS-STARTPTS"
            mux_cmd = [ffmpeg, "-y", "-i", str(silent_clip), "-i", str(audio),
                       "-af", audio_filter, "-map", "0:v:0", "-map", "1:a:0",
                       "-t", f"{duration:.3f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                       "-ar", "22050", "-movflags", "+faststart", str(clip)]
            subprocess.run(mux_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            scene_clips.append((clip, duration))

        # If narration needs more room than the nominal timings, preserve it while respecting 50 sec.
        total_duration = sum(duration for _, duration in scene_clips)
        if total_duration > 50.0:
            raise RuntimeError("The narration is too long for a 50-second video. Please shorten the property details or use fewer words in highlights.")

        concat_file = work_dir / "concat.txt"
        concat_file.write_text("".join(
            f"file '{str(clip).replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n"
            for clip, _duration in scene_clips
        ), encoding="utf-8")
        subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
                        "-c", "copy", "-movflags", "+faststart", str(output_path)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not output_path.exists() or output_path.stat().st_size < 10000:
            raise RuntimeError("MP4 export failed or output file is unexpectedly small.")
        probe = subprocess.run([ffmpeg, "-i", str(output_path)], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
        if "Audio:" not in (probe.stderr or ""):
            raise RuntimeError("The exported MP4 has no audio stream. Voice-over could not be embedded.")
        return output_path
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        property_name = request.form.get("property_name", "").strip()
        location = request.form.get("location", "").strip()
        price = request.form.get("price", "").strip()
        property_type = request.form.get("property_type", "").strip()
        bedrooms = request.form.get("bedrooms", "").strip()
        bathrooms = request.form.get("bathrooms", "").strip()
        area = request.form.get("area", "").strip()
        highlights = request.form.get("highlights", "").strip()
        contact = request.form.get("contact", "").strip()
        photo_labels_raw = request.form.get("photo_labels", "").strip()
        photo_labels = [x.strip() for x in photo_labels_raw.split(",") if x.strip()]
        uploaded = request.files.getlist("photos")

        if not all([property_name, location, price, property_type, contact]):
            flash("Please fill all required property details.", "error")
            return redirect(url_for("index"))
        photos = [f for f in uploaded if f and f.filename]
        if not MIN_IMAGES <= len(photos) <= MAX_IMAGES:
            flash("Please upload between 4 and 8 property photos, as required by the assignment.", "error")
            return redirect(url_for("index"))

        saved = []
        seen_hashes = set()
        job_id = uuid.uuid4().hex[:10]
        import hashlib
        for i, file in enumerate(photos, 1):
            ext = Path(file.filename).suffix.lower()
            if ext not in ALLOWED:
                flash("Only JPG, JPEG, PNG, and WEBP images are supported.", "error")
                return redirect(url_for("index"))
            name = f"{job_id}_{i:02d}{ext}"
            path = UPLOAD_DIR / name
            file.save(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in seen_hashes:
                path.unlink(missing_ok=True)
                continue
            seen_hashes.add(digest)
            saved.append(path)
        if not MIN_IMAGES <= len(saved) <= MAX_IMAGES:
            for path in saved:
                path.unlink(missing_ok=True)
            flash("Please upload 4–8 distinct photos. Exact duplicate files are removed automatically.", "error")
            return redirect(url_for("index"))

        # Keep specs in the opening; keep the middle-scene highlight list separate to avoid repetition.
        facts = highlights
        if photo_labels and len(photo_labels) != len(saved):
            for path in saved:
                path.unlink(missing_ok=True)
            flash("Enter one room label per uploaded photo, in the same order. Example: Balcony, Exterior, Kitchen, Bedroom.", "error")
            return redirect(url_for("index"))

        details = {
            "property_name": property_name, "location": location, "price": price,
            "property_type": property_type, "bedrooms": bedrooms, "bathrooms": bathrooms, "area": area,
            "highlights": facts, "contact": contact, "photo_labels": photo_labels
        }
        out = OUTPUT_DIR / f"{job_id}_property_ad.mp4"
        try:
            build_ad_video(saved, details, out)
            flash("Your property advertisement is ready. The MP4 includes voice-over and scene captions.", "success")
            return render_template("index.html", video_url=url_for("output_file", filename=out.name),
                                   download_url=url_for("download_file", filename=out.name))
        except Exception as exc:
            app.logger.exception("Video generation failed")
            flash(f"Could not create video: {exc}", "error")
        finally:
            for path in saved:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
        return redirect(url_for("index"))
    return render_template("index.html")


@app.route("/outputs/<path:filename>")
def output_file(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=False)


@app.route("/download/<path:filename>")
def download_file(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=False, use_reloader=False)
