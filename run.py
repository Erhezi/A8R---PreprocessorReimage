"""Entry point for the Contract Atlas preprocessor app.

Usage:
  Development:  python run.py
  Production:   python run.py production
"""

import sys
from preprocessorEC import create_app

config_name = sys.argv[1] if len(sys.argv) > 1 else "development"
app = create_app(config_name)

if __name__ == "__main__":
    if config_name == "production":
        from waitress import serve

        port = 8090
        print(f"Starting Waitress on port {port}...")
        serve(app, host="0.0.0.0", port=port)
    else:
        app.run(debug=True, port=5000)
