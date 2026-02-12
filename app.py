#!/usr/bin/env python3
"""
Vashon Ferry Display - Backend
Fetches WSF ferry schedules and serves them to the display
"""

from flask import Flask, jsonify, render_template
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
import os
import re
from typing import Dict, List, Any

app = Flask(__name__)
CORS(app)

# Get API key from environment variable
API_KEY = os.environ.get('WSF_API_KEY', '')

# WSF API endpoints
BASE_URL = "https://www.wsdot.wa.gov/ferries/api/schedule/rest"

# Route IDs - these need to be determined from the API
# We'll fetch route details to find the correct IDs for:
# - Vashon-Fauntleroy 
# - Tahlequah-Point Defiance

# Terminal IDs (based on URL patterns)
TERMINALS = {
    'fauntleroy': 9,
    'vashon': 22,
    'tahlequah': 21,
    'point_defiance': 16
}


def get_todays_date():
    """Get today's date in YYYY-MM-DD format"""
    return datetime.now().strftime('%Y-%m-%d')


def parse_dotnet_date(date_string: str) -> datetime:
    """
    Parse .NET JSON date format: /Date(1769601900000-0800)/
    Returns a datetime object
    """
    # Extract the timestamp (milliseconds since epoch)
    match = re.search(r'/Date\((\d+)([-+]\d{4})?\)/', date_string)
    if match:
        timestamp_ms = int(match.group(1))
        # Convert milliseconds to seconds
        timestamp_s = timestamp_ms / 1000
        return datetime.fromtimestamp(timestamp_s)
    else:
        # Fallback to ISO format parsing
        return datetime.fromisoformat(date_string.replace('Z', '+00:00'))


def detect_boats_running(departing_id: int, arriving_id: int) -> Dict[str, Any]:
    """
    Analyze schedule to determine how many boats are running on a route.
    Returns number of boats and confidence level.
    
    Strategy:
    1. Get next 10+ sailings
    2. Count unique vessel names
    3. Analyze time intervals between sailings
    """
    try:
        date = get_todays_date()
        url = f"{BASE_URL}/schedule/{date}/{departing_id}/{arriving_id}?apiaccesscode={API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        vessels = set()
        times = []
        
        if 'TerminalCombos' in data and data['TerminalCombos']:
            for combo in data['TerminalCombos']:
                if 'Times' in combo and combo['Times']:
                    for time_slot in combo['Times'][:15]:  # Look at first 15 sailings
                        # Collect vessel names
                        vessel_name = time_slot.get('VesselName', '')
                        if vessel_name:
                            vessels.add(vessel_name)
                        
                        # Collect departure times
                        if 'DepartingTime' in time_slot:
                            try:
                                dep_time = parse_dotnet_date(time_slot['DepartingTime'])
                                times.append(dep_time)
                            except:
                                pass
        
        # Calculate average interval between sailings (in minutes)
        intervals = []
        for i in range(len(times) - 1):
            interval = (times[i + 1] - times[i]).total_seconds() / 60
            if 10 < interval < 120:  # Filter out anomalies
                intervals.append(interval)
        
        avg_interval = sum(intervals) / len(intervals) if intervals else 0
        
        # Determine number of boats
        # 2-boat service: typically 30-40 min intervals
        # 3-boat service: typically 20-25 min intervals
        boat_count = len(vessels) if vessels else None
        
        if not boat_count and avg_interval:
            if avg_interval < 27:
                boat_count = 3
            else:
                boat_count = 2
        
        return {
            'boat_count': boat_count,
            'unique_vessels': list(vessels),
            'avg_interval_minutes': round(avg_interval, 1) if avg_interval else None,
            'confidence': 'high' if len(vessels) >= 2 else 'medium'
        }
        
    except Exception as e:
        print(f"Error detecting boats: {e}")
        return {
            'boat_count': None,
            'unique_vessels': [],
            'avg_interval_minutes': None,
            'confidence': 'low'
        }


def get_routes():
    """Fetch all available routes to find our route IDs"""
    try:
        date = get_todays_date()
        url = f"{BASE_URL}/routes/{date}?apiaccesscode={API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching routes: {e}")
        return []


def get_schedule_by_terminals(departing_id: int, arriving_id: int) -> Dict[str, Any]:
    """
    Fetch schedule for a specific terminal combination
    Returns the next 3 sailings
    """
    try:
        date = get_todays_date()
        url = f"{BASE_URL}/schedule/{date}/{departing_id}/{arriving_id}?apiaccesscode={API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Extract the next 3 upcoming sailings
        now = datetime.now()
        upcoming_sailings = []
        
        departing_name = ''
        arriving_name = ''
        
        if 'TerminalCombos' in data and data['TerminalCombos']:
            for combo in data['TerminalCombos']:
                departing_name = combo.get('DepartingTerminalName', '')
                arriving_name = combo.get('ArrivingTerminalName', '')
                
                if 'Times' in combo and combo['Times']:
                    for time_slot in combo['Times']:
                        if 'DepartingTime' in time_slot:
                            # Parse the departure time (handles .NET JSON date format)
                            dep_time_str = time_slot['DepartingTime']
                            try:
                                dep_time = parse_dotnet_date(dep_time_str)
                            except Exception as parse_error:
                                print(f"Date parsing error for {dep_time_str}: {parse_error}")
                                continue
                            
                            # Only include future sailings
                            if dep_time > now:
                                sailing_info = {
                                    'departure_time': dep_time.strftime('%I:%M %p'),
                                    'arriving_time': time_slot.get('ArrivingTime', ''),
                                    'vessel': time_slot.get('VesselName', 'Ferry'),
                                    'annotation': time_slot.get('AnnotationIndexes', [])
                                }
                                upcoming_sailings.append(sailing_info)
                                
                                if len(upcoming_sailings) >= 3:
                                    break
                if len(upcoming_sailings) >= 3:
                    break
        
        return {
            'success': True,
            'sailings': upcoming_sailings[:3],
            'departing': departing_name,
            'arriving': arriving_name
        }
        
    except Exception as e:
        print(f"Error fetching schedule: {e}")
        return {
            'success': False,
            'error': str(e),
            'sailings': []
        }


@app.route('/')
def index():
    """Serve the main display page"""
    return render_template('index.html')


@app.route('/api/ferries')
def get_ferry_data():
    """
    API endpoint to fetch current ferry schedules
    Returns next 3 sailings for both routes
    Only checks boat count for Vashon-Fauntleroy (Point Defiance only runs 1 boat)
    """
    
    # Route 1: Vashon-Fauntleroy (both directions)
    vashon_to_fauntleroy = get_schedule_by_terminals(
        TERMINALS['vashon'], 
        TERMINALS['fauntleroy']
    )
    fauntleroy_to_vashon = get_schedule_by_terminals(
        TERMINALS['fauntleroy'], 
        TERMINALS['vashon']
    )
    
    # Detect how many boats are running on Vashon-Fauntleroy route
    vf_boat_analysis = detect_boats_running(
        TERMINALS['vashon'],
        TERMINALS['fauntleroy']
    )
    
    # Route 2: Tahlequah-Point Defiance (both directions)
    # This route only runs 1 boat, so no need to detect
    tahlequah_to_pt_defiance = get_schedule_by_terminals(
        TERMINALS['tahlequah'], 
        TERMINALS['point_defiance']
    )
    pt_defiance_to_tahlequah = get_schedule_by_terminals(
        TERMINALS['point_defiance'], 
        TERMINALS['tahlequah']
    )
    
    return jsonify({
        'timestamp': datetime.now().isoformat(),
        'routes': {
            'vashon_fauntleroy': {
                'name': 'Vashon - Fauntleroy',
                'from_vashon': vashon_to_fauntleroy,
                'from_fauntleroy': fauntleroy_to_vashon,
                'boat_analysis': vf_boat_analysis
            },
            'tahlequah_point_defiance': {
                'name': 'Tahlequah - Point Defiance',
                'from_tahlequah': tahlequah_to_pt_defiance,
                'from_point_defiance': pt_defiance_to_tahlequah
            }
        }
    })


@app.route('/api/boat-status')
def get_boat_status():
    """
    Dedicated endpoint to check boat count on Vashon-Fauntleroy route
    (Point Defiance only runs 1 boat, so not checked)
    """
    vf_analysis = detect_boats_running(TERMINALS['vashon'], TERMINALS['fauntleroy'])
    
    return jsonify({
        'vashon_fauntleroy': vf_analysis
    })


@app.route('/api/test')
def test_api():
    """Test endpoint to verify API key and connectivity"""
    try:
        routes = get_routes()
        return jsonify({
            'success': True,
            'api_key_configured': bool(API_KEY),
            'routes_found': len(routes) if isinstance(routes, list) else 0
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


if __name__ == '__main__':
    # Check for API key
    if not API_KEY:
        print("=" * 60)
        print("WARNING: No WSF_API_KEY environment variable set!")
        print("Please register at: https://www.wsdot.wa.gov/traffic/api/")
        print("Then set it with: export WSF_API_KEY='your_key_here'")
        print("=" * 60)
    
    # Run the server
    app.run(host='0.0.0.0', port=5000, debug=True)
