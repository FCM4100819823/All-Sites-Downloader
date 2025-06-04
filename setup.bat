@echo off
echo 🚀 Setting up Universal Video Downloader...

:: Create virtual environment
echo 📦 Creating virtual environment...
python -m venv venv

:: Activate virtual environment
echo 🔌 Activating virtual environment...
call venv\Scripts\activate

:: Install dependencies
echo 📥 Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

:: Create necessary directories
echo 📁 Creating directories...
if not exist "downloads" mkdir downloads
if not exist "flask_session" mkdir flask_session

:: Set environment variables
echo 🔧 Setting up environment...
set FLASK_APP=app.py
set FLASK_ENV=development

echo ✅ Setup complete!
echo.
echo 🎯 To run the application:
echo 1. Activate virtual environment:
echo    venv\Scripts\activate
echo 2. Run the app:
echo    python app.py
echo.
echo 🌐 The app will be available at: http://localhost:5000
echo.
echo Press any key to start the application now...
pause >nul

:: Start the application
echo 🚀 Starting the application...
python app.py