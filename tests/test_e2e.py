import os
import sys
import threading
import time
import uvicorn
import json
from unittest.mock import patch
from playwright.sync_api import sync_playwright

# Import the FastAPI app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class MockMessage:
    def __init__(self, content):
        self.content = content

call_count = 0

def mock_get_llm_response(messages):
    global call_count
    
    # Check if this is a brief generation
    if any("Review the following patient intake conversation" in m.get('content', '') for m in messages):
        content = json.dumps({
            "chief_complaint": "Headache",
            "hpi": "Started 2 days ago, throbbing pain",
            "ros": "No nausea or vomiting"
        })
        return content
        
    # Normal chat flow
    stages = ['CHIEF_COMPLAINT', 'HPI', 'FOCUSED_ROS', 'CLARIFICATION', 'COMPLETE']
    if call_count < len(stages):
        next_stage = stages[call_count]
        agent_message = f"Mocked message asking about {next_stage}."
        if next_stage == 'COMPLETE':
            agent_message = "Thank you, the intake is complete."
        content = json.dumps({
            "agent_message": agent_message,
            "next_stage": next_stage
        })
    else:
        content = json.dumps({
            "agent_message": "Intake is already complete.",
            "next_stage": "COMPLETE"
        })
    
    call_count += 1
    return content

def run_server():
    # Use config and server to allow graceful shutdown if needed,
    # though daemon=True is usually enough for a script
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import main
    uvicorn.run(main.app, host="127.0.0.1", port=8001, log_level="error")

def test_chat_flow():
    global call_count
    call_count = 0
    
    # Start server
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)  # Wait for server to be ready
    
    with patch('main.get_llm_response', side_effect=mock_get_llm_response):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            # Ensure videos directory exists
            os.makedirs("videos", exist_ok=True)
            context = browser.new_context(record_video_dir="videos/")
            page = context.new_page()
            
            page.goto("http://localhost:8001/")
            
            # Wait for greeting message (from startIntake in app.js)
            page.wait_for_selector(".agent-message", timeout=10000)
            
            # Interact with the chat
            for i in range(6):
                # Count current agent messages
                prev_count = page.evaluate("document.querySelectorAll('.agent-message').length")
                
                page.fill("#user-input", f"User mock response {i}")
                page.click("#send-btn")
                
                # Wait for new agent message
                page.wait_for_function(f"document.querySelectorAll('.agent-message').length > {prev_count}", timeout=10000)
                time.sleep(0.5)
                
                # If system message appears, the intake is complete
                if page.locator(".system-message").count() > 1:
                    break
            
            # Wait for brief section
            page.wait_for_selector("#brief-section:not(.hidden)", timeout=10000)
            
            # Verify brief content
            assert "Headache" in page.locator("#brief-cc").inner_text()
            
            # Close context first to ensure video is saved
            context.close()
            browser.close()

if __name__ == "__main__":
    test_chat_flow()
    print("E2E Test completed successfully.")
