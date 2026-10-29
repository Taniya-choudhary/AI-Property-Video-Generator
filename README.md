# AI Property Video Generator — Promotional Video Edition

## What it does
- Accepts 4–8 JPG, JPEG, PNG, or WEBP property photos.
- Creates a vertical MP4 with gentle zoom motion, short fade transitions, room-title overlays, a designed information panel, and one continuous voice-over.
- Opens with property name, property type, location, asking price, and supplied size/bedroom details.
- Describes each photo using the room labels provided in upload order. Supplying labels is recommended because AI image captioning can misclassify rooms.
- Narrates matching features alongside the relevant photo (bedrooms with bedroom photos, bathrooms with bathroom photos, kitchen features with kitchen photos, and parking/security with parking or exterior photos). The final photo includes a contact / site-visit call to action.
- Targets around 6 seconds per photo, with a total duration of 30–48 seconds for 4–8 photos (maximum 50 seconds).
- Exports a downloadable MP4.

## Windows quick start
1. Extract this ZIP to a normal folder such as `Downloads\AI_Property_Video_Generator_Complete`.
2. Double-click `setup.bat` and wait until setup completes.
3. Double-click `run.bat`.
4. Open `http://127.0.0.1:5000` in your browser if it does not open automatically.
5. Enter property details, select 4–8 photos, and enter one room label per photo in the same order (for example: `Balcony, Exterior, Kitchen, Bedroom`).
6. Click **Generate AI property advertisement** and review the final video before publishing.

## Important notes
- The first run may need an internet connection to download the BLIP image-captioning model.
- Voice-over uses the Windows local speech API; installed voices and speaking speed can affect the final duration.
- Only enter verified property information. The app does not independently verify price, area, ownership, amenities, or other claims.
- This is a local development app, not a production-hosted service.
- Do not upload API keys, passwords, or private customer information to a public repository.
