import sys
import threading
import time
import webview
from app import app

def run_flask():
    # Run the Flask app on localhost on port 5000. Disable debug mode and reloader.
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    # Start Flask server in a background daemon thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Give the server a moment to spin up
    time.sleep(1.2)
    
    # Start the webview window loading localhost
    # Setting width=1280 and height=800 for optimal PC desktop experience
    webview.create_window("Aurora V.75", "http://127.0.0.1:5000", width=1280, height=800)
    webview.start()
