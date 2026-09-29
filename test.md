docker run --rm -v "${PWD}/load-tests:/load-tests" grafana/k6 run -e BASE_URL=https://hackathon.bebsapati.com /load-tests/dashboard.js

ssh root@167.99.226.149 "python3 /opt/fsirp/tools/validate_scenarios.py"

ssh root@167.99.226.149 "cat /root/load-tests/results/scenario_evidence.json"
