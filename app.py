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

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
Session(app)

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

def download_video(url, download_id, format_type='best'):
    try:
        progress_obj = download_progress[download_id]
        
        # Configure yt-dlp options
        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, f'{download_id}_%(title)s.%(ext)s'),
            'progress_hooks': [lambda d: progress_hook(d, download_id)],
            'extractaudio': format_type == 'audio',
            'audioformat': 'mp3' if format_type == 'audio' else None,
            'format': 'bestaudio/best' if format_type == 'audio' else 'best',
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
            ydl.download([url])
            
    except Exception as e:
        progress_obj.status = 'error'
        progress_obj.error = str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url')
    format_type = data.get('format', 'video')  # video, audio
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    # Generate unique download ID
    download_id = str(uuid.uuid4())
    
    # Initialize progress tracking
    download_progress[download_id] = DownloadProgress(download_id)
    
    # Start download in background thread
    thread = threading.Thread(target=download_video, args=(url, download_id, format_type))
    thread.daemon = True
    thread.start()
    
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
    
    return send_file(
        progress_obj.file_path,
        as_attachment=True,
        download_name=progress_obj.filename
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
def get_video_info():
    """Get video information without downloading"""
    data = request.get_json()
    url = data.get('url')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Format file sizes
            formats = []
            if 'formats' in info:
                for f in info['formats']:
                    if f.get('filesize') or f.get('filesize_approx'):
                        size = f.get('filesize') or f.get('filesize_approx')
                        formats.append({
                            'format_id': f.get('format_id'),
                            'ext': f.get('ext'),
                            'quality': f.get('format_note', ''),
                            'filesize': size,
                            'filesize_human': format_bytes(size) if size else 'Unknown'
                        })
            
            return jsonify({
                'title': info.get('title'),
                'duration': info.get('duration'),
                'uploader': info.get('uploader'),
                'view_count': info.get('view_count'),
                'description': info.get('description', '')[:500] + '...' if info.get('description') else '',
                'thumbnail': info.get('thumbnail'),
                'formats': formats[:10],  # Top 10 formats
                'upload_date': info.get('upload_date'),
                'website': info.get('extractor_key')
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def format_bytes(bytes_value):
    """Convert bytes to human readable format"""
    if bytes_value == 0:
        return "0B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while bytes_value >= 1024 and i < len(size_names) - 1:
        bytes_value /= 1024.0
        i += 1
    
    return f"{bytes_value:.1f} {size_names[i]}"

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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)