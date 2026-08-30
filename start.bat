@echo off
echo Starting Finance Controller Agent Services...

echo ==============================================
echo 1. Starting Python FastAPI Engine (Port 8000)
echo ==============================================
start cmd /k "title Engine (FastAPI) && cd engine && (.\venv\Scripts\python.exe main.py || python main.py)"

echo ==============================================
echo 2. Starting Node.js Express Server (Port 5000)
echo ==============================================
start cmd /k "title Server (Express) && cd server && npm start"

echo ==============================================
echo 3. Starting React Frontend (Port 5173)
echo ==============================================
start cmd /k "title Client (React) && cd client && npm run dev"

echo.
echo All services are launching in separate windows!
echo Please check each window for any startup errors.
echo You can now open your browser to http://localhost:5173
pause
