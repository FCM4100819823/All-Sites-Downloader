import os
import uuid
import json
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_file, session
from flask_session import Session
import yt_dlp
from urllib.parse import urlparse
import re
import time
from concurrent.futures import ThreadPoolExecutor
import requests
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
Session(app)

# Track application start time for uptime calculations
app.start_time = time.time()

# Global storage for download progress
download_progress = {}
download_history = {}

DOWNLOAD_FOLDER = os.path.join(os.getcwd(), 'downloads')
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

class DownloadProgress:
    def __init__(self, download_id):
        self.download_id = download_id
        self.status = 'preparing'
        self.progress = 0
        self.filename = ''
        self.filesize = 0
        self.downloaded = 0
        self.speed = 0
        self.eta = 0
        self.error = None
        self.completed = False
        self.file_path = None

def progress_hook(d, download_id):
    if download_id not in download_progress:
        return
    
    progress_obj = download_progress[download_id]
    
    if d['status'] == 'downloading':
        progress_obj.status = 'downloading'
        progress_obj.filename = d.get('filename', 'Unknown')
        
        if 'total_bytes' in d:
            progress_obj.filesize = d['total_bytes']
            progress_obj.downloaded = d['downloaded_bytes']
            progress_obj.progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
        elif 'total_bytes_estimate' in d:
            progress_obj.filesize = d['total_bytes_estimate']
            progress_obj.downloaded = d['downloaded_bytes']
            progress_obj.progress = (d['downloaded_bytes'] / d['total_bytes_estimate']) * 100
        
        progress_obj.speed = d.get('speed', 0)
        progress_obj.eta = d.get('eta', 0)
        
    elif d['status'] == 'finished':
        progress_obj.status = 'completed'
        progress_obj.progress = 100
        progress_obj.completed = True
        progress_obj.file_path = d['filename']
        progress_obj.filename = os.path.basename(d['filename'])

executor = ThreadPoolExecutor(max_workers=5)  # Allow up to 5 parallel downloads

def download_video(url, download_id, format_type='best', max_retries=3, retry_delay=5):
    """
    Download a video with automatic retry functionality
    
    Args:
        url: URL to download
        download_id: Unique ID for tracking the download
        format_type: Format to download (video or audio)
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds
    """
    retry_count = 0
    progress_obj = download_progress[download_id]
    
    while retry_count <= max_retries:
        try:
            # Use a clean, readable filename template
            ydl_opts = {
                'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
                'progress_hooks': [lambda d: progress_hook(d, download_id)],
                'extractaudio': format_type == 'audio',
                'audioformat': 'mp3' if format_type == 'audio' else None,
                'format': 'bestaudio/best' if format_type == 'audio' else 'bestvideo+bestaudio/best',
                'merge_output_format': 'mp4' if format_type == 'video' else None,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                progress_obj.status = 'extracting_info'
                info = ydl.extract_info(url, download=False)
                
                # Store video info
                progress_obj.title = info.get('title', 'Unknown')
                progress_obj.duration = info.get('duration', 0)
                progress_obj.uploader = info.get('uploader', 'Unknown')
                progress_obj.view_count = info.get('view_count', 0)
                
                # Start download
                progress_obj.status = 'starting_download'
                result = ydl.download([url])
                
                # After download, find the actual file path
                info = ydl.extract_info(url, download=False)
                ext = info.get('ext', 'mp4')
                safe_title = info.get('title', 'video')
                filename = f"{safe_title}.{ext}"
                file_path = os.path.join(DOWNLOAD_FOLDER, filename)
                progress_obj.file_path = file_path
                progress_obj.filename = filename

                # If we get here without exception, download was successful
                return
                
        except Exception as e:
            retry_count += 1
            progress_obj.status = 'retrying' if retry_count <= max_retries else 'error'
            progress_obj.error = f"Error: {str(e)}" + (f" (Retry {retry_count}/{max_retries})" if retry_count <= max_retries else "")
            
            # If we still have retries left, wait and then retry
            if retry_count <= max_retries:
                time.sleep(retry_delay)
                # Increase delay for each retry (exponential backoff)
                retry_delay *= 1.5
            else:
                # Final failure
                progress_obj.error = f"Failed after {max_retries} retries: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url')
    format_type = data.get('format', 'video')  # video, audio
    format_id = data.get('format_id')
    playlist_urls = data.get('playlist_urls')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    # Generate unique download ID
    download_id = str(uuid.uuid4())
    
    # Initialize progress tracking
    download_progress[download_id] = DownloadProgress(download_id)
    
    def run_download():
        progress_obj = download_progress[download_id]
        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
            'progress_hooks': [lambda d: progress_hook(d, download_id)],
        }
        if format_id:
            ydl_opts['format'] = format_id
        elif format_type == 'audio':
            ydl_opts['format'] = 'bestaudio/best'
        else:
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if playlist_urls:
                    for u in playlist_urls:
                        ydl.download([u])
                else:
                    ydl.download([url])
        except Exception as e:
            progress_obj.status = 'error'
            progress_obj.error = str(e)
    executor.submit(run_download)
    
    # Store in session for user tracking
    if 'downloads' not in session:
        session['downloads'] = []
    session['downloads'].append(download_id)
    
    return jsonify({'download_id': download_id})

@app.route('/api/progress/<download_id>')
def get_progress(download_id):
    if download_id not in download_progress:
        return jsonify({'error': 'Download not found'}), 404
    
    progress_obj = download_progress[download_id]
    
    return jsonify({
        'status': progress_obj.status,
        'progress': progress_obj.progress,
        'filename': progress_obj.filename,
        'filesize': progress_obj.filesize,
        'downloaded': progress_obj.downloaded,
        'speed': progress_obj.speed,
        'eta': progress_obj.eta,
        'error': progress_obj.error,
        'completed': progress_obj.completed,
        'title': getattr(progress_obj, 'title', ''),
        'duration': getattr(progress_obj, 'duration', 0),
        'uploader': getattr(progress_obj, 'uploader', ''),
        'view_count': getattr(progress_obj, 'view_count', 0)
    })

@app.route('/api/download_file/<download_id>')
def download_file(download_id):
    if download_id not in download_progress:
        return jsonify({'error': 'Download not found'}), 404
    
    progress_obj = download_progress[download_id]
    
    if not progress_obj.completed or not progress_obj.file_path:
        return jsonify({'error': 'Download not completed'}), 400
    
    if not os.path.exists(progress_obj.file_path):
        return jsonify({'error': 'File not found'}), 404
    
    # Guess MIME type based on extension
    ext = os.path.splitext(progress_obj.filename)[1].lower()
    mimetype = 'application/octet-stream'
    if ext == '.mp4':
        mimetype = 'video/mp4'
    elif ext == '.mp3':
        mimetype = 'audio/mpeg'
    elif ext == '.webm':
        mimetype = 'video/webm'
    elif ext == '.m4a':
        mimetype = 'audio/mp4'
    elif ext == '.wav':
        mimetype = 'audio/wav'
    elif ext == '.aac':
        mimetype = 'audio/aac'
    elif ext == '.flac':
        mimetype = 'audio/flac'
    
    return send_file(
        progress_obj.file_path,
        as_attachment=True,
        download_name=progress_obj.filename,
        mimetype=mimetype
    )

@app.route('/api/supported_sites')
def supported_sites():
    """Get list of supported sites from yt-dlp"""
    try:
        with yt_dlp.YoutubeDL() as ydl:
            extractors = ydl.list_extractors()
            # Get popular sites
            popular_sites = [
                'youtube', 'twitter', 'instagram', 'tiktok', 'facebook',
                'vimeo', 'dailymotion', 'twitch', 'reddit', 'pinterest',
                'linkedin', 'soundcloud', 'spotify', 'bandcamp'
            ]
            
            supported = []
            for extractor in extractors:
                name = extractor.IE_NAME.lower()
                if any(site in name for site in popular_sites):
                    supported.append({
                        'name': extractor.IE_NAME,
                        'description': getattr(extractor, 'IE_DESC', ''),
                        'website': name
                    })
            
            return jsonify({'sites': supported[:50]})  # Return top 50
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/video_info', methods=['POST'])
def video_info():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    ydl_opts = {'quiet': True, 'skip_download': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            # For playlists, info['entries'] is a list of video dicts
            formats = info.get('formats', [])
            format_list = [
                {
                    'format_id': f.get('format_id'),
                    'format_note': f.get('format_note'),
                    'resolution': f.get('resolution'),
                    'ext': f.get('ext'),
                    'filesize': f.get('filesize')
                } for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none'
            ]
            entries = []
            if 'entries' in info and info['entries']:
                for entry in info['entries']:
                    entries.append({
                        'title': entry.get('title'),
                        'url': entry.get('webpage_url') or entry.get('url')
                    })
            return jsonify({
                'title': info.get('title'),
                'uploader': info.get('uploader'),
                'duration': info.get('duration'),
                'view_count': info.get('view_count'),
                'description': info.get('description'),
                'website': info.get('extractor_key'),
                'thumbnail': info.get('thumbnail'),
                'formats': format_list,
                'entries': entries
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/my_downloads')
def my_downloads():
    """Get user's download history"""
    if 'downloads' not in session:
        return jsonify({'downloads': []})
    
    downloads = []
    for download_id in session['downloads']:
        if download_id in download_progress:
            progress_obj = download_progress[download_id]
            downloads.append({
                'id': download_id,
                'status': progress_obj.status,
                'filename': progress_obj.filename,
                'title': getattr(progress_obj, 'title', ''),
                'completed': progress_obj.completed,
                'error': progress_obj.error
            })
    
    return jsonify({'downloads': downloads})

@app.route('/api/update_yt_dlp', methods=['POST'])
def update_yt_dlp():
    """Check and update yt-dlp to the latest version."""
    try:
        result = os.system('pip install -U yt-dlp')
        if result == 0:
            return jsonify({'message': 'yt-dlp updated successfully'}), 200
        else:
            return jsonify({'error': 'Failed to update yt-dlp'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload_to_drive', methods=['POST'])
def upload_to_drive():
    """Upload a downloaded file to Google Drive."""
    data = request.get_json()
    download_id = data.get('download_id')

    if download_id not in download_progress:
        return jsonify({'error': 'Download not found'}), 404

    progress_obj = download_progress[download_id]

    if not progress_obj.completed or not progress_obj.file_path:
        return jsonify({'error': 'Download not completed'}), 400

    try:
        # Google Drive API setup
        SCOPES = ['https://www.googleapis.com/auth/drive.file']
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', SCOPES)
        service = build('drive', 'v3', credentials=creds)

        # Upload file
        file_metadata = {'name': progress_obj.filename}
        media = MediaFileUpload(progress_obj.file_path, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()

        return jsonify({'message': 'File uploaded to Google Drive', 'file_id': file.get('id')}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download_subtitles', methods=['POST'])
def download_subtitles():
    """Download subtitles for a video."""
    data = request.get_json()
    url = data.get('url')
    language = data.get('language', 'en')

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    try:
        ydl_opts = {
            'writesubtitles': True,
            'subtitleslangs': [language],
            'skip_download': True,
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s')
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({'message': 'Subtitles downloaded', 'title': info.get('title')}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/convert_audio', methods=['POST'])
def convert_audio():
    """Convert a downloaded video to a specific audio format."""
    data = request.get_json()
    download_id = data.get('download_id')
    audio_format = data.get('format', 'mp3')

    if download_id not in download_progress:
        return jsonify({'error': 'Download not found'}), 404

    progress_obj = download_progress[download_id]

    if not progress_obj.completed or not progress_obj.file_path:
        return jsonify({'error': 'Download not completed'}), 400

    try:
        output_file = os.path.splitext(progress_obj.file_path)[0] + f'.{audio_format}'
        os.system(f'ffmpeg -i "{progress_obj.file_path}" "{output_file}"')

        return jsonify({'message': 'Audio converted', 'output_file': output_file}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/drag_and_drop', methods=['POST'])
def drag_and_drop():
    """Handle drag-and-drop URL input with rate limiting"""
    data = request.get_json()
    urls = data.get('urls', [])

    if not urls:
        return jsonify({'error': 'No URLs provided'}), 400

    # Limit to 10 URLs at a time to prevent overload
    if len(urls) > 10:
        urls = urls[:10]

    responses = []
    
    # Use rate limiting for batch downloads
    delay_seconds = 0
    for url in urls:
        download_id = str(uuid.uuid4())
        download_progress[download_id] = DownloadProgress(download_id)
        
        # Schedule with a delay for rate limiting
        threading.Timer(delay_seconds, lambda u=url, d=download_id: executor.submit(download_video, u, d)).start()
        
        # Add 2 seconds delay between each download to prevent overload
        delay_seconds += 2
        
        responses.append({
            'url': url, 
            'download_id': download_id,
            'estimated_start_time': delay_seconds
        })
        
        # Add to user session
        if 'downloads' not in session:
            session['downloads'] = []
        session['downloads'].append(download_id)

    return jsonify({
        'message': f'Processing {len(urls)} URLs with rate limiting',
        'downloads': responses
    }), 200

@app.route('/api/set_speed_limit', methods=['POST'])
def set_speed_limit():
    """Set a download speed limit."""
    data = request.get_json()
    speed_limit = data.get('speed_limit')
    
    if not speed_limit:
        return jsonify({'error': 'Speed limit is required'}), 400
    
    try:
        # Parse to integer KB/s
        speed_limit_int = int(speed_limit)
        
        # Update the default options for yt-dlp
        os.environ['YDL_RATE_LIMIT'] = str(speed_limit_int)
        
        return jsonify({
            'message': f'Speed limit set to {speed_limit_int} KB/s',
            'speed_limit': speed_limit_int
        }), 200
    except ValueError:
        return jsonify({'error': 'Speed limit must be a valid number'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/export_history_json')
def export_history_json():
    """Export download history as JSON"""
    if 'downloads' not in session:
        return jsonify({'error': 'No download history found'}), 404
    
    history = []
    for download_id in session['downloads']:
        if download_id in download_progress:
            progress_obj = download_progress[download_id]
            history.append({
                'id': download_id,
                'title': getattr(progress_obj, 'title', ''),
                'uploader': getattr(progress_obj, 'uploader', ''),
                'status': progress_obj.status,
                'filename': progress_obj.filename,
                'filesize': progress_obj.filesize,
                'progress': progress_obj.progress,
                'completed': progress_obj.completed,
                'error': progress_obj.error,
                'download_time': datetime.now().isoformat()
            })
    
    # Create a response with JSON content
    response = app.response_class(
        response=json.dumps(history, indent=4),
        status=200,
        mimetype='application/json'
    )
    response.headers["Content-Disposition"] = "attachment; filename=download_history.json"
    return response

@app.route('/api/export_history_csv')
def export_history_csv():
    """Export download history as CSV"""
    if 'downloads' not in session:
        return jsonify({'error': 'No download history found'}), 404
    
    # Create CSV content
    csv_content = "id,title,uploader,status,filename,filesize,progress,completed,error\n"
    for download_id in session['downloads']:
        if download_id in download_progress:
            progress_obj = download_progress[download_id]
            # Escape double quotes in fields for CSV format
            title = getattr(progress_obj, "title", "").replace('"', '""')
            uploader = getattr(progress_obj, "uploader", "").replace('"', '""')
            error_msg = str(progress_obj.error).replace('"', '""') if progress_obj.error else ""
            
            csv_content += f'"{download_id}","{title}","{uploader}","{progress_obj.status}","{progress_obj.filename}","{progress_obj.filesize}","{progress_obj.progress}","{progress_obj.completed}","{error_msg}"\n'
    
    # Create a response with CSV content
    response = app.response_class(
        response=csv_content,
        status=200,
        mimetype='text/csv'
    )
    response.headers["Content-Disposition"] = "attachment; filename=download_history.csv"
    return response

@app.route('/api/system_stats')
def system_stats():
    """Get system statistics"""
    stats = {
        'total_downloads': len(session.get('downloads', [])),
        'active_downloads': len([d for d in download_progress.values() if d.status == 'downloading']),
        'completed_downloads': len([d for d in download_progress.values() if d.status == 'completed']),
        'failed_downloads': len([d for d in download_progress.values() if d.status == 'error']),
        'total_downloaded_bytes': sum(d.filesize for d in download_progress.values() if d.completed),
        'average_speed': sum(d.speed for d in download_progress.values() if d.speed) / max(1, len([d for d in download_progress.values() if d.speed])),
        'server_uptime': int(time.time() - app.start_time) if hasattr(app, 'start_time') else 0,
    }
    
    return jsonify(stats)

@app.route('/api/clear_history', methods=['POST'])
def clear_history():
    """Clear download history"""
    data = request.get_json()
    download_id = data.get('download_id')
    
    if download_id:
        # Clear just one specific download
        if download_id in session.get('downloads', []):
            session['downloads'].remove(download_id)
            
            # Also remove from progress tracker if completed or error
            if download_id in download_progress:
                progress_obj = download_progress[download_id]
                if progress_obj.completed or progress_obj.status == 'error':
                    del download_progress[download_id]
            
            return jsonify({'message': f'Download {download_id} removed from history'})
    else:
        # Clear all completed or error downloads
        if 'downloads' in session:
            # Create a new list with only active downloads
            active_downloads = []
            for download_id in session['downloads']:
                if download_id in download_progress:
                    progress_obj = download_progress[download_id]
                    if not (progress_obj.completed or progress_obj.status == 'error'):
                        active_downloads.append(download_id)
                    elif progress_obj.completed or progress_obj.status == 'error':
                        # Clean up completed/error downloads from the progress tracker
                        del download_progress[download_id]
            
            # Update session with only active downloads
            session['downloads'] = active_downloads
        
        return jsonify({'message': 'Download history cleared'})
    
    return jsonify({'error': 'Invalid request'}), 400

@app.route('/api/retry_download', methods=['POST'])
def retry_download():
    """Retry a failed download"""
    data = request.get_json()
    download_id = data.get('download_id')
    
    if not download_id:
        return jsonify({'error': 'Download ID is required'}), 400
    
    if download_id not in download_progress:
        return jsonify({'error': 'Download not found'}), 404
    
    progress_obj = download_progress[download_id]
    
    # Only retry if it's an error
    if progress_obj.status != 'error':
        return jsonify({'error': 'Can only retry failed downloads'}), 400
    
    # Reset progress
    progress_obj.status = 'preparing'
    progress_obj.progress = 0
    progress_obj.downloaded = 0
    progress_obj.error = None
    progress_obj.completed = False
    
    # Get the original URL (need to store this in the progress object)
    url = data.get('url')
    if not url:
        return jsonify({'error': 'URL is required for retry'}), 400
    
    # Start the download again
    executor.submit(download_video, url, download_id, data.get('format', 'video'))
    
    return jsonify({'message': 'Download restarted', 'download_id': download_id})

@app.route('/api/cancel_download', methods=['POST'])
def cancel_download():
    """Cancel an active download"""
    data = request.get_json()
    download_id = data.get('download_id')
    
    if not download_id:
        return jsonify({'error': 'Download ID is required'}), 400
    
    if download_id not in download_progress:
        return jsonify({'error': 'Download not found'}), 404
    
    progress_obj = download_progress[download_id]
    
    # Only cancel if it's not already completed or error
    if progress_obj.status in ['completed', 'error']:
        return jsonify({'error': 'Cannot cancel a completed or failed download'}), 400
    
    # Mark as cancelled
    progress_obj.status = 'cancelled'
    progress_obj.error = 'Download cancelled by user'
    
    return jsonify({'message': 'Download cancelled', 'download_id': download_id})

@app.route('/api/search_youtube', methods=['POST'])
def search_youtube():
    """Search YouTube videos using yt-dlp."""
    data = request.get_json()
    query = data.get('query')
    limit = min(data.get('limit', 10), 30)  # Limit max results to 30
    
    if not query:
        return jsonify({'error': 'Search query is required'}), 400
    
    try:
        # Format the YouTube search URL
        search_url = f"ytsearch{limit}:{query}"
        
        # Use yt-dlp to perform the search
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,  # Don't download the videos, just get info
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(search_url, download=False)
            
            # Process and format the results
            videos = []
            if 'entries' in search_results:
                for entry in search_results['entries']:
                    videos.append({
                        'id': entry.get('id'),
                        'title': entry.get('title'),
                        'url': f"https://www.youtube.com/watch?v={entry.get('id')}",
                        'thumbnail': entry.get('thumbnail'),
                        'uploader': entry.get('uploader'),
                        'duration': entry.get('duration'),
                        'view_count': entry.get('view_count')
                    })
            
            return jsonify({
                'query': query,
                'results': videos
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/options')
def get_options():
    """Return available configuration options and current settings."""
    options = {
        'max_parallel_downloads': 5,
        'speed_limit': os.environ.get('YDL_RATE_LIMIT', None),
        'supported_formats': ['mp4', 'mp3', 'webm', 'm4a', 'wav', 'aac', 'flac'],
        'default_download_folder': DOWNLOAD_FOLDER,
        'history_export_formats': ['json', 'csv'],
        'theme_modes': ['light', 'dark', 'auto'],
        'max_batch_urls': 10
    }
    return jsonify(options)

# Set the app start time when the app is initialized
app.start_time = time.time()

if __name__ == "__main__":
    import sys
    port = int(os.environ.get("PORT", 5000))
    # Allow port override via command-line: python app.py 8080
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except Exception:
            pass
    app.run(debug=True, host="0.0.0.0", port=port)