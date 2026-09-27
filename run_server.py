"""
run_server.py — One-click launcher for Delhivery Graph-Enhanced ETA Platform
"""

import os
import sys
import threading
import time
import webbrowser
import uvicorn

def open_browser():
    time.sleep(1.5)
    url = "http://localhost:8000"
    print(f"\n[+] Opening Delhivery Platform in your browser: {url}\n")
    webbrowser.open(url)

if __name__ == "__main__":
    app_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_dir)
    print("=" * 70)
    print("  DELHIVERY GRAPH-ENHANCED ETA & NETWORK INTELLIGENCE PLATFORM")
    print("=" * 70)
    print(f"Starting server from: {app_dir}")
    print("Server URL: http://localhost:8000")
    print("API Documentation: http://localhost:8000/docs")
    print("Press Ctrl+C to stop the server.")
    print("=" * 70)

    # Launch browser in separate thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Start FastAPI with Uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
