@echo off
title Delhivery Graph-Enhanced ETA Platform
echo ======================================================================
echo    DELHIVERY GRAPH-ENHANCED ETA & NETWORK INTELLIGENCE PLATFORM
echo ======================================================================
cd /d "%~dp0"
echo Starting platform on http://localhost:8000 ...
py -3.14 run_server.py
pause
