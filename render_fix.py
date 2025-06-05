# Add to your app.py or main server file

# Ensure yt-dlp is up to date when app starts on Render
import subprocess
import os
import sys

# Get absolute path to ensure we can find the script in production
def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# Update yt-dlp on startup, especially for cloud environments
def update_yt_dlp():
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

# Call this function when your app starts
update_yt_dlp()

# Configure yt-dlp with additional options for cloud environments
def get_yt_dlp_options(download_folder, download_id, format_id=None, format_type='video'):
    options = {
        'outtmpl': os.path.join(download_folder, '%(title)s.%(ext)s'),
        'progress_hooks': [lambda d: progress_hook(d, download_id)],
        # Add proxy support if needed
        # 'proxy': 'socks5://user:pass@host:port',
        # Add more forgiving options for cloud environments
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'ignoreerrors': True,
        'no_warnings': True,
        # Use HTTP source addresses for better compatibility
        'source_addresses': ['0.0.0.0'],
        # Geo bypass for region restrictions
        'geo_bypass': True,
        'geo_bypass_country': 'US',  # Use US as default, change if needed
    }
    
    if format_id:
        options['format'] = format_id
    elif format_type == 'audio':
        options['format'] = 'bestaudio/best'
        options['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        options['format'] = 'bestvideo+bestaudio/best'
    
    return options

# Use this function in your download route instead of creating options directly