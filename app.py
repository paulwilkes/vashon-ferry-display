#!/usr/bin/env python3
"""
Vashon Ferry Display V2 - Backend
Server-side caching, background data fetching, vessel tracking, alerts.
Browser requests never hit WSF directly.
"""

from flask import Flask, jsonify, render_template
from flask_cors import CORS
import requests
from datetime import datetime, timedelta, timezone
import os
import re
import time
import threading
from zoneinfo import ZoneInfo
import logging
from typing import Dict, List, Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_KEY = os.environ.get('WSF_API_KEY', '')

# Timezone — all times are Pacific
PACIFIC = ZoneInfo('America/Los_Angeles')

def now_pacific() -> datetime:
    """Get current time in Pacific timezone, as a naive datetime for comparison with WSF dates."""
    return datetime.now(PACIFIC).replace(tzinfo=None)

# WSF API base URLs
SCHEDULE_URL = "https://www.wsdot.wa.gov/ferries/api/schedule/rest"
VESSELS_URL = "https://www.wsdot.wa.gov/ferries/api/vessels/rest"
TERMINALS_URL = "https://www.wsdot.wa.gov/ferries/api/terminals/rest"

# Terminal IDs
TERMINALS = {
    'fauntleroy': 9,
    'vashon': 22,
    'tahlequah': 21,
    'point_defiance': 16,
}

# All terminal IDs we care about (for filtering vessel data)
VASHON_TERMINAL_IDS = set(TERMINALS.values())

# Cache timing
BACKGROUND_POLL_INTERVAL = 30   # seconds between background fetches
CACHE_MAX_STALE = 300           # 5 minutes max before forced refetch
VESSEL_POLL_INTERVAL = 15       # vessel data refreshes faster
API_TIMEOUT = 10                # seconds per API call
RETRY_DELAY = 2                 # seconds between retry attempts

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('ferry-display')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_dotnet_date(date_string: str) -> Optional[datetime]:
    """Parse .NET JSON date format: /Date(1769601900000-0800)/
    Always returns a naive datetime in Pacific time."""
    if not date_string:
        return None
    match = re.search(r'/Date\((\d+)([-+]\d{4})?\)/', date_string)
    if match:
        timestamp_ms = int(match.group(1))
        # Convert UTC timestamp to Pacific, then strip tzinfo for naive comparison
        utc_dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        return utc_dt.astimezone(PACIFIC).replace(tzinfo=None)
    try:
        dt = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        return dt.astimezone(PACIFIC).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def wsf_get(url: str, retries: int = 1) -> Optional[Any]:
    """Fetch from WSF API with timeout and retry."""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, timeout=API_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < retries:
                log.warning(f"WSF API retry ({attempt+1}) for {url.split('?')[0]}: {e}")
                time.sleep(RETRY_DELAY)
            else:
                log.error(f"WSF API failed after {retries+1} attempts: {url.split('?')[0]}: {e}")
                return None


# ---------------------------------------------------------------------------
# WSFCache — server-side in-memory cache with background fetching
# ---------------------------------------------------------------------------

class WSFCache:
    """
    In-memory cache for all WSF data. A background thread polls the APIs
    on a fixed interval so Flask endpoints read from cache instantly.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            'schedules': {},        # key: "dept_id-arr_id" -> schedule data
            'vessel_locations': [],  # filtered to Vashon routes
            'alerts': [],
            'bulletins': {},        # key: terminal_id -> list of bulletins
            'boat_analysis': {},    # key: "dept_id-arr_id" -> analysis
        }
        self._meta = {
            'schedules_at': None,
            'vessels_at': None,
            'alerts_at': None,
            'bulletins_at': None,
            'last_flush_schedule': None,
            'last_flush_vessels': None,
            'last_flush_terminals': None,
            'errors': [],
        }
        self._running = False
        self._threads: List[threading.Timer] = []

    # -- public read methods (called by Flask endpoints) --

    def get_ferries(self) -> Dict[str, Any]:
        """Return the full ferry data payload for /api/ferries."""
        with self._lock:
            now = now_pacific()
            schedules = self._data['schedules']
            alerts = self._data['alerts']
            bulletins = self._data['bulletins']
            boat_analysis = self._data['boat_analysis']
            fetched_at = self._meta['schedules_at']

            stale = False
            if fetched_at:
                age = (now - fetched_at).total_seconds()
                stale = age > 90  # consider stale after 90s
            else:
                stale = True

            # Build direction data
            def direction_data(dept_key, arr_key):
                cache_key = f"{TERMINALS[dept_key]}-{TERMINALS[arr_key]}"
                cached = schedules.get(cache_key, {})
                return {
                    'success': bool(cached.get('sailings')),
                    'sailings': cached.get('sailings', []),
                    'departing': cached.get('departing', ''),
                    'arriving': cached.get('arriving', ''),
                    'error': cached.get('error'),
                }

            vf_key = f"{TERMINALS['vashon']}-{TERMINALS['fauntleroy']}"

            return {
                'timestamp': now.isoformat(),
                'fetched_at': fetched_at.isoformat() if fetched_at else None,
                'stale': stale,
                'routes': {
                    'vashon_fauntleroy': {
                        'name': 'Vashon - Fauntleroy',
                        'from_vashon': direction_data('vashon', 'fauntleroy'),
                        'from_fauntleroy': direction_data('fauntleroy', 'vashon'),
                        'boat_analysis': boat_analysis.get(vf_key, {}),
                    },
                    'tahlequah_point_defiance': {
                        'name': 'Tahlequah - Point Defiance',
                        'from_tahlequah': direction_data('tahlequah', 'point_defiance'),
                        'from_point_defiance': direction_data('point_defiance', 'tahlequah'),
                    },
                },
                'alerts': alerts,
                'bulletins': {str(k): v for k, v in bulletins.items()},
            }

    def get_vessels(self) -> Dict[str, Any]:
        """Return vessel locations for /api/vessels."""
        with self._lock:
            return {
                'timestamp': now_pacific().isoformat(),
                'fetched_at': self._meta['vessels_at'].isoformat() if self._meta['vessels_at'] else None,
                'stale': self._is_stale('vessels_at'),
                'vessels': self._data['vessel_locations'],
            }

    def get_health(self) -> Dict[str, Any]:
        """Return cache/health info for /api/health."""
        with self._lock:
            def fmt(dt):
                if not dt:
                    return None
                return {
                    'time': dt.isoformat(),
                    'age_seconds': round((now_pacific() - dt).total_seconds()),
                }
            return {
                'api_key_configured': bool(API_KEY),
                'cache': {
                    'schedules': fmt(self._meta['schedules_at']),
                    'vessels': fmt(self._meta['vessels_at']),
                    'alerts': fmt(self._meta['alerts_at']),
                    'bulletins': fmt(self._meta['bulletins_at']),
                },
                'recent_errors': self._meta['errors'][-10:],
                'background_running': self._running,
            }

    def _is_stale(self, meta_key: str) -> bool:
        ts = self._meta.get(meta_key)
        if not ts:
            return True
        return (now_pacific() - ts).total_seconds() > 90

    # -- background fetching --

    def start(self):
        """Start background polling threads."""
        if self._running:
            return
        self._running = True
        log.info("Starting background data fetchers")
        # Initial fetch immediately
        threading.Thread(target=self._fetch_schedules_and_alerts, daemon=True).start()
        threading.Thread(target=self._fetch_vessels, daemon=True).start()
        # Then schedule recurring
        self._schedule_recurring(self._fetch_schedules_and_alerts, BACKGROUND_POLL_INTERVAL)
        self._schedule_recurring(self._fetch_vessels, VESSEL_POLL_INTERVAL)

    def stop(self):
        """Stop background threads."""
        self._running = False
        for t in self._threads:
            t.cancel()
        self._threads.clear()

    def _schedule_recurring(self, func, interval):
        """Run func every interval seconds."""
        def loop():
            while self._running:
                time.sleep(interval)
                if self._running:
                    try:
                        func()
                    except Exception as e:
                        log.error(f"Background fetch error: {e}")
        t = threading.Thread(target=loop, daemon=True)
        t.start()

    def _record_error(self, msg: str):
        with self._lock:
            self._meta['errors'].append({
                'time': now_pacific().isoformat(),
                'message': msg,
            })
            # Keep only last 50 errors
            if len(self._meta['errors']) > 50:
                self._meta['errors'] = self._meta['errors'][-50:]

    # -- schedule + alerts + bulletins fetch --

    def _fetch_schedules_and_alerts(self):
        """Fetch schedules, alerts, and bulletins from WSF."""
        # Check cacheflushdate first
        flush = wsf_get(f"{SCHEDULE_URL}/cacheflushdate?apiaccesscode={API_KEY}")
        if flush and flush == self._meta.get('last_flush_schedule'):
            # No change, skip refetch unless stale
            if not self._is_stale('schedules_at'):
                return
        if flush:
            self._meta['last_flush_schedule'] = flush

        # Fetch schedules for all 4 directions
        directions = [
            ('vashon', 'fauntleroy'),
            ('fauntleroy', 'vashon'),
            ('tahlequah', 'point_defiance'),
            ('point_defiance', 'tahlequah'),
        ]

        new_schedules = {}
        all_sailings_for_analysis = {}  # for boat detection

        for dept_key, arr_key in directions:
            dept_id = TERMINALS[dept_key]
            arr_id = TERMINALS[arr_key]
            cache_key = f"{dept_id}-{arr_id}"

            # Use false for onlyRemaining so delayed sailings aren't dropped
            url = f"{SCHEDULE_URL}/scheduletoday/{dept_id}/{arr_id}/false?apiaccesscode={API_KEY}"
            data = wsf_get(url)

            if data is not None:
                parsed = self._parse_schedule(data)
                new_schedules[cache_key] = parsed
                all_sailings_for_analysis[cache_key] = parsed.get('all_times', [])
            else:
                self._record_error(f"Schedule fetch failed: {dept_key}->{arr_key}")
                # Keep existing cached data for this direction
                with self._lock:
                    existing = self._data['schedules'].get(cache_key)
                    if existing:
                        new_schedules[cache_key] = existing

        # Boat analysis from schedule data (no extra API call)
        vf_key = f"{TERMINALS['vashon']}-{TERMINALS['fauntleroy']}"
        fv_key = f"{TERMINALS['fauntleroy']}-{TERMINALS['vashon']}"
        boat_analysis = {}
        vf_data = new_schedules.get(vf_key, {})
        fv_data = new_schedules.get(fv_key, {})
        if vf_data or fv_data:
            boat_analysis[vf_key] = self._analyze_boats(vf_data, fv_data)

        # Fetch alerts
        alerts = []
        alerts_data = wsf_get(f"{SCHEDULE_URL}/alerts?apiaccesscode={API_KEY}")
        if alerts_data is not None:
            alerts = self._parse_alerts(alerts_data)

        # Fetch terminal bulletins
        bulletins = {}
        for name, tid in TERMINALS.items():
            url = f"{TERMINALS_URL}/terminalbulletins/{tid}?apiaccesscode={API_KEY}"
            data = wsf_get(url)
            if data is not None:
                bulletins[tid] = self._parse_bulletins(data)

        # Update cache atomically
        with self._lock:
            self._data['schedules'] = new_schedules
            self._data['alerts'] = alerts
            self._data['bulletins'] = bulletins
            self._data['boat_analysis'] = boat_analysis
            self._meta['schedules_at'] = now_pacific()
            self._meta['alerts_at'] = now_pacific()
            self._meta['bulletins_at'] = now_pacific()

        log.info(f"Schedules updated ({len(new_schedules)} directions, {len(alerts)} alerts)")

    def _parse_schedule(self, data: Any) -> Dict[str, Any]:
        """Parse WSF schedule response into our format."""
        now = now_pacific()
        upcoming = []
        all_times_for_analysis = []
        departing_name = ''
        arriving_name = ''

        # Between midnight and 3 AM, don't show morning sailings yet.
        # This keeps the display showing "last sailing" context overnight.
        hide_morning = now.hour < 3

        # scheduletoday returns a list of TerminalCombos or similar
        combos = []
        if isinstance(data, dict):
            combos = data.get('TerminalCombos', [])
        elif isinstance(data, list):
            combos = data

        for combo in combos:
            if not isinstance(combo, dict):
                continue
            departing_name = combo.get('DepartingTerminalName', departing_name)
            arriving_name = combo.get('ArrivingTerminalName', arriving_name)

            for time_slot in combo.get('Times', []):
                dep_time = parse_dotnet_date(time_slot.get('DepartingTime', ''))
                if not dep_time:
                    continue

                vessel = time_slot.get('VesselName', 'Ferry')
                all_times_for_analysis.append({
                    'time': dep_time,
                    'vessel': vessel,
                })

                # Include future sailings, PLUS recent past sailings that
                # may be delayed (within 30 min window). The frontend will
                # check vessel data to see if they've actually departed.
                minutes_ago = (now - dep_time).total_seconds() / 60
                is_future = dep_time > now
                is_recent_past = 0 < minutes_ago <= 30

                # Between midnight-3AM, skip morning sailings (before 5AM)
                if hide_morning and dep_time.hour < 5 and is_future:
                    continue

                if is_future or is_recent_past:
                    upcoming.append({
                        'departure_time': dep_time.strftime('%I:%M %p'),
                        'departure_iso': dep_time.isoformat(),
                        'vessel': vessel,
                        'scheduled_past': is_recent_past,
                        'last_sailing': False,
                        'annotation': time_slot.get('AnnotationIndexes', []),
                    })

        # Mark the very last future sailing of the day
        if upcoming:
            upcoming[-1]['last_sailing'] = True

        # Only send the first 4 to the frontend
        display_sailings = upcoming[:4]

        # If the last sailing is beyond index 3, check if it's in view
        # and propagate the flag to whichever is last in the display list
        if len(upcoming) > 4:
            # Last sailing flag is on the final entry which isn't shown
            # Only mark it if it's within our display window
            pass
        elif upcoming:
            # All sailings fit; last one already marked
            pass

        return {
            'success': True,
            'sailings': display_sailings,
            'departing': departing_name,
            'arriving': arriving_name,
            'all_times': all_times_for_analysis,
        }

    def _analyze_boats(self, vashon_data: Dict, fauntleroy_data: Dict) -> Dict[str, Any]:
        """Derive boat count from already-fetched schedule data."""
        vessels = set()
        times = []

        for data in [vashon_data, fauntleroy_data]:
            for entry in data.get('all_times', []):
                if entry.get('vessel'):
                    vessels.add(entry['vessel'])
                if entry.get('time'):
                    times.append(entry['time'])

        # Sort and calculate intervals for one direction
        dir_times = sorted(
            [e['time'] for e in vashon_data.get('all_times', []) if e.get('time')]
        )
        intervals = []
        for i in range(len(dir_times) - 1):
            gap = (dir_times[i + 1] - dir_times[i]).total_seconds() / 60
            if 10 < gap < 120:
                intervals.append(gap)

        avg_interval = sum(intervals) / len(intervals) if intervals else 0
        boat_count = len(vessels) if vessels else None

        if not boat_count and avg_interval:
            boat_count = 3 if avg_interval < 27 else 2

        return {
            'boat_count': boat_count,
            'unique_vessels': list(vessels),
            'avg_interval_minutes': round(avg_interval, 1) if avg_interval else None,
            'confidence': 'high' if len(vessels) >= 2 else 'medium',
        }

    # Keywords that indicate operationally important alerts/bulletins
    # (cancellations, delays, out of service routes, wait times)
    _IMPORTANT_KEYWORDS = [
        'cancel', 'out of service', 'suspended', 'delay',
        'wait time', 'extended wait', 'long wait',
        'not operating', 'no service', 'service alert',
        'emergency', 'closed', 'closure',
        'disabled', 'one-boat', '1-boat', 'reduced service',
        'mechanical', 'breakdown', 'vessel swap',
        'weather hold',
    ]

    # Keywords that indicate noise we want to filter OUT
    _NOISE_KEYWORDS = [
        'elevator', 'escalator', 'restroom',
        'sailing schedule started', 'spring schedule', 'summer schedule',
        'winter schedule', 'fall schedule',
        'open house', 'public meeting', 'survey',
        'opinion group', 'frog',
        'preservation project', 'construction planning',
        'terminal preservation',
        'sign up', 'join the',
        'wind advisory', 'high wind', 'small craft advisory',
        'gale warning', 'tide advisory',
    ]

    def _is_operationally_important(self, text: str) -> bool:
        """Check if alert/bulletin text is operationally important."""
        lower = text.lower()
        # Reject noise first
        if any(noise in lower for noise in self._NOISE_KEYWORDS):
            return False
        # Accept if it contains important keywords
        return any(kw in lower for kw in self._IMPORTANT_KEYWORDS)

    def _parse_alerts(self, data: Any) -> List[Dict[str, Any]]:
        """Parse alerts response, filter to Vashon-relevant + operationally important."""
        if not isinstance(data, list):
            return []
        alerts = []
        for alert in data:
            if not isinstance(alert, dict):
                continue
            alert_text = (
                alert.get('AlertFullTitle', '') +
                alert.get('AlertDescription', '') +
                alert.get('AlertFullText', '')
            )
            # Must mention our routes
            lower = alert_text.lower()
            is_our_route = any(term in lower for term in [
                'vashon', 'fauntleroy', 'tahlequah', 'point defiance',
                'all routes', 'system',
            ])
            if is_our_route and self._is_operationally_important(alert_text):
                publish_date = parse_dotnet_date(alert.get('PublishDate', ''))
                alerts.append({
                    'title': alert.get('AlertFullTitle', alert.get('BulletinTitle', '')),
                    'description': alert.get('AlertDescription', alert.get('AlertFullText', '')),
                    'publish_date': publish_date.isoformat() if publish_date else None,
                })
        return alerts

    def _parse_bulletins(self, data: Any) -> List[Dict[str, str]]:
        """Parse terminal bulletins, only keep operationally important ones."""
        if not isinstance(data, list):
            if isinstance(data, dict):
                bulletins_list = data.get('Bulletins', [])
                if not bulletins_list:
                    return []
                data = bulletins_list
            else:
                return []
        results = []
        for b in data:
            if not isinstance(b, dict):
                continue
            title = b.get('BulletinTitle', '')
            text = b.get('BulletinText', '')
            combined = title + ' ' + text
            if (title or text) and self._is_operationally_important(combined):
                results.append({'title': title, 'text': text})
        return results

    # -- vessel locations fetch --

    def _fetch_vessels(self):
        """Fetch real-time vessel locations from WSF."""
        # Check cacheflushdate
        flush = wsf_get(f"{VESSELS_URL}/cacheflushdate?apiaccesscode={API_KEY}")
        if flush and flush == self._meta.get('last_flush_vessels'):
            if not self._is_stale('vessels_at'):
                return
        if flush:
            self._meta['last_flush_vessels'] = flush

        url = f"{VESSELS_URL}/vessellocations?apiaccesscode={API_KEY}"
        data = wsf_get(url)

        if data is None:
            self._record_error("Vessel locations fetch failed")
            return

        if not isinstance(data, list):
            self._record_error(f"Unexpected vessel data type: {type(data)}")
            return

        # Filter to vessels on Vashon routes
        relevant = []
        for v in data:
            if not isinstance(v, dict):
                continue
            dept_id = v.get('DepartingTerminalID')
            arr_id = v.get('ArrivingTerminalID')
            in_service = v.get('InService', False)

            # Include if vessel is servicing any of our terminals
            if in_service and (dept_id in VASHON_TERMINAL_IDS or arr_id in VASHON_TERMINAL_IDS):
                eta = parse_dotnet_date(v.get('Eta', ''))
                left_dock = parse_dotnet_date(v.get('LeftDock', ''))
                scheduled = parse_dotnet_date(v.get('ScheduledDeparture', ''))

                # Calculate delay
                delay_minutes = None
                if eta and scheduled:
                    delay = (eta - scheduled).total_seconds() / 60
                    if delay > 2:  # only report delays > 2 min
                        delay_minutes = round(delay)

                relevant.append({
                    'vessel_id': v.get('VesselID'),
                    'vessel_name': v.get('VesselName', ''),
                    'latitude': v.get('Latitude'),
                    'longitude': v.get('Longitude'),
                    'speed': v.get('Speed'),
                    'heading': v.get('Heading'),
                    'at_dock': v.get('AtDock', False),
                    'departing_terminal_id': dept_id,
                    'departing_terminal': v.get('DepartingTerminalName', ''),
                    'arriving_terminal_id': arr_id,
                    'arriving_terminal': v.get('ArrivingTerminalName', ''),
                    'eta': eta.isoformat() if eta else None,
                    'left_dock': left_dock.isoformat() if left_dock else None,
                    'scheduled_departure': scheduled.isoformat() if scheduled else None,
                    'delay_minutes': delay_minutes,
                    'status_message': v.get('VesselWatchMsg', ''),
                })

        with self._lock:
            self._data['vessel_locations'] = relevant
            self._meta['vessels_at'] = now_pacific()

        log.info(f"Vessels updated ({len(relevant)} on Vashon routes)")


# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------

app = Flask(__name__)
CORS(app)
cache = WSFCache()


@app.after_request
def add_cache_headers(response):
    """Short browser cache to reduce redundant requests, but not stale."""
    if response.content_type and 'application/json' in response.content_type:
        response.headers['Cache-Control'] = 'public, max-age=10'
    return response


@app.route('/')
def index():
    """Serve the main display page."""
    return render_template('index.html')


@app.route('/api/ferries')
def api_ferries():
    """
    Main data endpoint. Returns schedules, alerts, bulletins, boat analysis.
    Reads from server cache — instant response, never hits WSF.
    """
    return jsonify(cache.get_ferries())


@app.route('/api/vessels')
def api_vessels():
    """
    Lightweight vessel locations for the incoming ferry animation.
    Polled every ~20s by the frontend.
    """
    return jsonify(cache.get_vessels())


@app.route('/api/health')
def api_health():
    """Cache status and diagnostics for debugging on the Pi."""
    return jsonify(cache.get_health())


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def start_background_fetcher():
    """Start the cache's background polling. Called once at app startup."""
    if not API_KEY:
        log.warning("=" * 60)
        log.warning("No WSF_API_KEY set! Register at: https://www.wsdot.wa.gov/traffic/api/")
        log.warning("Set with: export WSF_API_KEY='your_key_here'")
        log.warning("=" * 60)
    cache.start()


# Start background fetcher when module loads (works with both `python app.py` and gunicorn)
start_background_fetcher()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
