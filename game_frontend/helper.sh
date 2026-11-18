Stop-Process -Id 5236 -Force
Stop-Process -Id 14292 -Force
Stop-Process -Id 11720 -Force

netstat -ano | findstr :8003
netstat -ano | findstr :5173


Set-Location C:\Users\Rita\Desktop\world_simulator
.\.venv\Scripts\python.exe -m uvicorn map_test:app --host 127.0.0.1 --port 8003 --app-dir .\at_the_beginning


Set-Location C:\Users\Rita\Desktop\world_simulator\game_frontend
$env:VITE_BACKEND_URL = "http://127.0.0.1:8003"
npm run dev -- --host=127.0.0.1 --port=5173

http://127.0.0.1:5173