# 1. API Load & Stress Test (k6)
docker run --rm -v "${PWD}/load-tests:/load-tests" grafana/k6 run -e BASE_URL=https://hackathon.bebsapati.com /load-tests/dashboard.js

# 2. Scenario & Resilience Test (Run directly from Windows PowerShell)
python tools\validate_scenarios.py --backend-url https://hackathon.bebsapati.com --admin-url http://167.99.226.149:8000

# 3. View Evidence JSON directly
cat load-tests/results/scenario_evidence.json
