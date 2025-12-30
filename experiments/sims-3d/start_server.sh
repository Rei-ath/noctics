#!/bin/bash
cd sims-3d
python -m http.server 8080 > server.log 2>&1 &
echo "Server started with PID $!"
