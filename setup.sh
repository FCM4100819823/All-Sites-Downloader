#!/bin/bash

# Universal Video Downloader Setup Script

echo "🚀 Setting up Universal Video Downloader..."

# Create virtual environment
echo "📦 Creating virtual environment..."
python -m venv venv

# Activate virtual environment
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

# Install dependencies
echo "📥 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p downloads
mkdir -p flask_session

# Set environment variables
echo "🔧 Setting up environment..."
export FLASK_APP=app.py
export FLASK_ENV=development

echo "✅ Setup complete!"
echo ""
echo "🎯 To run the application:"
echo "1. Activate virtual environment:"
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    echo "   source venv/Scripts/activate"
else
    echo "   source venv/bin/activate"
fi
echo "2. Run the app:"
echo "   python app.py"
echo ""
echo "🌐 The app will be available at: http://localhost:5000"