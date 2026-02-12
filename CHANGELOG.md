# Vashon Ferry Display — Changelog

A reconstructed history of all updates and iterations to the Vashon Ferry Display project, from initial concept through current state. This changelog was compiled from conversation history between Paul and Claude on February 12, 2026.

---

## v1.0 — Initial Build (Late January 2026)

**Core application created from scratch.**

### Backend (`app.py`)
- Flask web server serving ferry schedule data
- Integration with Washington State Ferries (WSF) API
- Terminal ID mapping for Vashon–Fauntleroy and Tahlequah–Point Defiance routes
- API key management via environment variable (`WSF_API_KEY`)
- `/api/ferries` endpoint returning schedule data for all four directions
- 60-second auto-refresh interval

### Frontend (`index.html`)
- Two-section layout: "The North End" (Vashon ↔ Fauntleroy) and "The South End" (Tahlequah ↔ Pt. Defiance)
- Next 3 upcoming sailings per direction with vessel names and departure times
- Blue "Last Updated" info box
- Custom typography: Playfair Display, Space Mono, Space Grotesk
- Yellow/teal color scheme

### Infrastructure
- `requirements.txt` (Flask, flask-cors, requests)
- `README.md` with Raspberry Pi hardware requirements and setup guide
- WSF API key registration instructions

---

## v1.1 — Bug Fixes (January 28, 2026)

### Issue 1: Date Parsing Error — FIXED
- **Error:** `Invalid isoformat string: '/Date(1769601900000-0800)/'`
- **Cause:** WSF API returns dates in .NET JSON format, not ISO format
- **Fix:** Added `parse_dotnet_date()` function to extract timestamps from `/Date(milliseconds-timezone)/` format

### Issue 2: Wrong Terminal IDs — FIXED
- **Error:** `400 Bad Request` for Tahlequah–Point Defiance route
- **Cause:** Incorrect terminal IDs (had Tahlequah = 23, Point Defiance = 1)
- **Fix:** Updated to correct IDs (Tahlequah = 21, Point Defiance = 16)

### Documentation
- Created initial `CHANGELOG.md` documenting these two fixes

---

## v1.2 — Boat Detection Feature (Late January 2026)

### Backend
- Added boat detection logic analyzing schedule data two ways:
  - Counting unique vessel names per route
  - Analyzing average time intervals between sailings (<27 min = 3-boat, >27 min = 2-boat)
- New `/api/boat-status` dedicated endpoint
- Confidence scoring (high/medium/low) based on data quality

### Frontend
- Boat status display under each route title showing count, vessel names, and interval
- Color-coded borders: teal (#70c1bb) for 3-boat service, coral (#d76662) for 2-boat
- Integrated into Paul's custom-styled index.html without breaking existing design

### Documentation
- `BOAT_DETECTION.md` explaining how detection works

---

## v1.3 — South End Optimization (Late January 2026)

**Removed boat detection for Point Defiance route** (always 1-boat service).

### Backend (`app.py`)
- Removed boat detection API calls for Tahlequah–Point Defiance route
- Removed `boat_analysis` from Point Defiance data in API response

### Frontend (`index.html`)
- Removed boat status display from "The South End" section
- Boat count only shows under "The North End"

### Performance
- Reduced from 4 API calls per refresh to 2
- Cleaner, more focused API response

### Documentation
- `OPTIMIZATION_SUMMARY.md`

---

## v1.4 — Ferry Header Illustration (Late January 2026)

**Added original SVG ferry illustration as page header.**

- Playful, geometric-style ferry on pink sky with blue water
- Yellow smoke puffs, blue birds, colorful passengers on deck
- Bold color palette: pink (#FFB5B5), blue (#4B6EDB), yellow (#FFE66D), coral (#FF6B6B)
- Full-width responsive SVG matching the display's color scheme
- Integrated as background header in `index.html`

---

## v1.5 — Weather Box Integration (Late January 2026)

**Added live weather display using Open-Meteo API.**

### Frontend
- Yellow weather info box on the right side, mirroring the blue update box on the left
- Displays: temperature (°F), conditions (text description), wind speed (knots)
- Weather data sourced from Open-Meteo API (free, no key required)
- Location hardcoded to Vashon Island, WA coordinates
- Weather updates every 5 minutes; ferry data still every 60 seconds
- `getWeatherDescription()` function converting weather codes to readable text

### Documentation
- `WEATHER_BOX_GUIDE.md`

---

## v1.6 — Weather-Reactive Header Illustrations (Late January 2026)

**Created 7 weather-specific SVG header variations.**

Each header keeps the ferry identical but changes atmospheric conditions:

| Header   | Sky/Mood                                    | Background Color       |
|----------|---------------------------------------------|------------------------|
| Clear    | Original pink sky, birds, calm water        | #FFB5B5 (pink)         |
| Cloudy   | Fluffy clouds in sky                        | #D9ACAC (muted pink)   |
| Overcast | Uniform gray sky, muted tones (PNW style)   | #C8C8C8 (gray)         |
| Fog      | Fog layers, muted colors                    | #E8D5D5 (light pink)   |
| Rain     | Dark sky, rain streaks, choppy water        | #B8A0A0 (dark pink)    |
| Snow     | Cool tones, falling snowflakes              | #C8D5E0 (cool gray)    |
| Windy    | Wind lines, tilted birds, sideways smoke    | #FFB5B5 (pink)         |
| Night    | Stars, moon, glowing windows, nav lights    | #1A1F3A (dark blue)    |

---

## v1.7 — Dynamic Weather Header System (Late January 2026)

**Automated header switching based on real-time weather and time of day.**

### Detection Logic
1. Check `is_day` from weather API → if night, use Night header (overrides all)
2. Check weather code: fog (45, 48), snow (71–77, 85–86), rain (51–67, 80–82, 95–99)
3. Check wind speed: >20 mph → Windy header
4. Cloudy/overcast (codes 2–3) → Cloudy header
5. Default → Clear header

### Implementation
- All 7 SVG headers embedded as JavaScript template strings (~85KB total)
- `determineHeaderType()` function mapping weather data to header selection
- `updateHeaderForWeather()` swaps SVG content and background color
- Smooth CSS transitions between background states
- Header checks every 5 minutes alongside weather updates

### Bug Fix: Z-Index Issue
- Info boxes (update time + weather) disappeared when header swapped
- **Cause:** `outerHTML` replacement removed the `.ferry-illustration` class
- **Fix:** Switched to `innerHTML` replacement to preserve container element and CSS classes

### Documentation
- `DYNAMIC_WEATHER_INSTRUCTIONS.md`
- `USAGE_GUIDE.md` with testing tips and customization guide

---

## v1.8 — Night Mode Text Styling (Late January 2026)

**Fixed text readability in night mode.**

| Text Element      | Day Color  | Night Color  |
|-------------------|------------|--------------|
| Route Titles      | Blue       | White        |
| Vessel Names      | Coral      | Yellow       |
| Ferry Times       | Blue       | White        |
| Direction Headers | Light Blue | Darker Blue  |

- Automatic class-based styling: `body.classList.add('night-mode')` when nighttime
- CSS overrides via `.night-mode` selectors
- Smooth transitions preserved

### Documentation
- `NIGHT_MODE_TEXT_FIX.md`

---

## v1.9 — Mac Development Environment (Late January 2026)

**Created local development workflow for editing on MacBook Pro before deploying to Pi.**

- `install-mac.sh` — Automated Mac setup (venv, dependencies, API key)
- `run-dev.sh` — Quick-start script for local development
- `README-MAC.md` — Mac development guide
- `API_REFERENCE.md` — WSF API documentation
- Recommended workflow: develop on Mac → SCP to Pi → restart service

---

## v2.0 — Raspberry Pi Deployment Package (February 1, 2026)

**Complete deployment package for Raspberry Pi.**

### Installation
- `install-pi.sh` — Automated installer handling:
  - System package updates
  - Python virtual environment and dependency installation
  - WSF API key configuration (`.env` file)
  - systemd service creation (`ferry-display.service`) for auto-start
  - Chromium kiosk mode configuration (fullscreen, no error dialogs)
  - Screen blanking disabled (`xset s off`, `xset -dpms`, `xset s noblank`)
  - `unclutter` to hide mouse cursor

### Documentation
- `QUICKSTART.md` — 5-minute setup guide
- `README.md` — Complete Pi deployment guide with troubleshooting
- Exit kiosk mode instructions (Alt+F4, Ctrl+Alt+F2, SSH)

### Paul's CSS Adjustments
- Paul made manual margin/padding tweaks to the CSS before final Pi deployment
- Display rotation configured via Pi GUI

---

## v2.1 — Animated Headers (February 10–12, 2026)

**Added CSS animations to all weather header illustrations.**

Work done in collaboration between Claude (claude.ai) and Claude Code.

### Clear (Original)
- Birds flapping wings at varied speeds (0.5–0.6s cycles)
- Ferry gently bobbing on waves (3s cycle)
- Smoke puffs fading and drifting upward in sequence
- Wave lines gently undulating

### Fog
- Fog layers drifting slowly across the scene
- Gentle boat bobbing, subtle wave motion

### Rain
- Falling rain streaks in two layers
- More pronounced boat bobbing
- Choppy waves, rain splashes pulsing on water surface

### Cloudy
- Fluffy clouds drifting slowly across sky
- Boat bobbing, gentle waves

### Snow
- Multiple layers of snowflakes falling at different speeds and sizes
- Boat bobbing, gentle waves

### Windy
- Fast-moving wind streaks across sky
- Smoke blown dramatically sideways
- Choppy waves with whitecaps and spray
- Tilted birds struggling in wind
- More pronounced boat bobbing

### Night
- Twinkling stars at different rates
- Blinking red/green navigation lights
- Blinking red mast light
- Pulsing window glow
- Moon reflection shimmering on water
- Boat bobbing, gentle waves

### Overcast
- Very subtle gray cloud patches drifting slowly (60+ second cycles)
- Boat bobbing, gentle waves

All animations are infinite CSS loops — performant and cross-browser compatible.

---

## Project File Structure (Current)

```
ferry-display/
├── app.py                  # Flask backend + WSF API integration
├── templates/
│   └── index.html          # Complete frontend (~85KB with embedded SVGs)
├── requirements.txt        # Python dependencies
├── install-pi.sh           # Raspberry Pi automated installer
├── install-mac.sh          # Mac development setup
├── run-dev.sh              # Mac quick-start script
├── .env                    # API key (not committed)
├── CHANGELOG.md            # This file
├── QUICKSTART.md           # 5-minute Pi setup
├── README.md               # Full Pi deployment guide
└── README-MAC.md           # Mac development guide
```

---

## Tech Stack

- **Backend:** Python 3 / Flask
- **Frontend:** Vanilla HTML/CSS/JavaScript with embedded SVG illustrations
- **APIs:** Washington State Ferries (WSF), Open-Meteo (weather)
- **Hardware:** Raspberry Pi 4 + HDMI display
- **Display:** Chromium in kiosk mode, systemd auto-start
