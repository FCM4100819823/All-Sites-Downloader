# render_fixes.py - Import this in your main app.py

import subprocess
import os
import sys
import time

def update_yt_dlp():
    """Update yt-dlp to the latest version - crucial for cloud hosting."""
    try:
        print("Updating yt-dlp...")
        result = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"], 
                                capture_output=True, text=True)
        print(f"yt-dlp update output: {result.stdout}")
        if result.returncode != 0:
            print(f"yt-dlp update error: {result.stderr}")
        return result.returncode == 0
    except Exception as e:
        print(f"Error updating yt-dlp: {str(e)}")
        return False

def enhanced_yt_dlp_options(base_options, format_id=None, format_type='video'):
    """
    Enhance yt-dlp options with settings that work better on cloud hosting.
    Accepts your existing options dict and enhances it.
    """
    # Keep your existing options
    options = base_options.copy()
    
    # Add cloud-friendly options
    cloud_options = {
        # More retries for cloud environments
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'ignoreerrors': True,
        'no_warnings': True,
        # Use HTTP source addresses for better compatibility
        'source_addresses': ['0.0.0.0'],
        # Geo bypass for region restrictions
        'geo_bypass': True,
        'geo_bypass_country': 'US',  # Use US as default
        # Add cookies for age-restricted content (auto-generates cookie file)
        'cookiefile': os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt'),
        # Add referer for some sites
        'referer': 'https://www.youtube.com/',
        # Try to avoid IP blocking
        'sleep_interval': 5,
        'max_sleep_interval': 10,
        'sleep_interval_requests': 1
    }
    
    # Update with cloud options
    options.update(cloud_options)
    
    # Handle format override if provided
    if format_id:
        options['format'] = format_id
    elif format_type == 'audio' and 'format' not in options:
        options['format'] = 'bestaudio/best'
        options['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    elif 'format' not in options:
        options['format'] = 'bestvideo+bestaudio/best'
    
    return options

def create_cookie_file():
    """Create a basic cookie file that can help with some restrictions."""
    cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
    if not os.path.exists(cookie_path):
        try:
            with open(cookie_path, 'w') as f:
                f.write("# Netscape HTTP Cookie File\n")
                f.write(".youtube.com\tTRUE\t/\tFALSE\t2147483647\tCONSENT\tYES+cb\n")
                f.write(".youtube.com\tTRUE\t/\tFALSE\t2147483647\tLOGIN_INFO\tdummy\n")
            print(f"Created cookie file at {cookie_path}")
        except Exception as e:
            print(f"Error creating cookie file: {str(e)}")

# Auto-updates yt-dlp and creates a cookie file when this module is imported
update_yt_dlp()
create_cookie_file()