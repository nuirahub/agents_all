pip install -r requirements.txt

python app.py
curl http://localhost:8000/health

curl -X POST http://localhost:8000/api/chat/completions ^
-H "Content-Type: application/json" ^
-d "{\"input\":\"Hello!\"}"

curl -X POST http://localhost:8000/api/chat/completions -H "Content-Type: application/json" -d "@request.json"
