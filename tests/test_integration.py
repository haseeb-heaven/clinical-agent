import pytest
import json
from fastapi.testclient import TestClient
from unittest.mock import patch
from main import app, sessions, Stage

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_sessions():
    sessions.clear()

def test_get_index():
    response = client.get("/")
    assert response.status_code == 200
    # Check if it returns the HTML content (FastAPI FileResponse)
    assert "text/html" in response.headers["content-type"]

@patch("main.get_llm_response")
def test_chat_endpoint_new_session(mock_llm):
    mock_llm.return_value = json.dumps({
        "agent_message": "Hello, how can I help?",
        "next_stage": "CHIEF_COMPLAINT"
    })
    
    response = client.post("/chat", json={"user_message": "Hi"})
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["agent_message"] == "Hello, how can I help?"
    assert data["stage"] == "CHIEF_COMPLAINT"
    
    # Verify session was created
    session_id = data["session_id"]
    assert session_id in sessions
    assert sessions[session_id].stage == Stage.CHIEF_COMPLAINT

@patch("main.get_llm_response")
def test_chat_endpoint_existing_session(mock_llm):
    session_id = "test-session"
    mock_llm.return_value = json.dumps({
        "agent_message": "Tell me more about the pain.",
        "next_stage": "HPI"
    })
    
    response = client.post("/chat", json={
        "session_id": session_id,
        "user_message": "My head hurts"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == session_id
    assert data["stage"] == "HPI"
    
    # Verify history
    assert len(sessions[session_id].history) == 2
    assert sessions[session_id].history[0].role == "user"
    assert sessions[session_id].history[1].role == "assistant"

@patch("main.get_llm_response")
def test_generate_brief_success(mock_llm):
    session_id = "complete-session"
    # Setup a complete session
    client.post("/chat", json={
        "session_id": session_id,
        "user_message": "Everything is done"
    })
    sessions[session_id].stage = Stage.COMPLETE
    
    mock_llm.return_value = json.dumps({
        "chief_complaint": "Headache",
        "hpi": "Started 2 days ago",
        "ros": "No other symptoms"
    })
    
    response = client.post("/brief", json={"session_id": session_id})
    assert response.status_code == 200
    data = response.json()
    assert data["chief_complaint"] == "Headache"
    assert data["hpi"] == "Started 2 days ago"
    assert data["ros"] == "No other symptoms"

def test_generate_brief_not_found():
    response = client.post("/brief", json={"session_id": "non-existent"})
    assert response.status_code == 404

@patch("main.get_llm_response")
def test_chat_error_handling(mock_llm):
    mock_llm.side_effect = Exception("LLM Error")
    response = client.post("/chat", json={"user_message": "Help"})
    assert response.status_code == 500
    assert "LLM Error" in response.json()["detail"]
