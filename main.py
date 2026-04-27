import os
import json
import uuid
import logging
import re
from enum import Enum
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from litellm import completion
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "app.log")

log_level_str = os.getenv("APP_LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)

logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="Clinical Intake Agent")

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure static directory exists relative to this file
base_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(base_dir, "static")
os.makedirs(static_dir, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def get_index():
    return FileResponse(os.path.join(static_dir, "index.html"))

# Enums and Models
class Stage(str, Enum):
    GREETING = "GREETING"
    CHIEF_COMPLAINT = "CHIEF_COMPLAINT"
    HPI = "HPI"
    FOCUSED_ROS = "FOCUSED_ROS"
    CLARIFICATION = "CLARIFICATION"
    COMPLETE = "COMPLETE"

class Message(BaseModel):
    role: str
    content: str

class SessionData(BaseModel):
    session_id: str
    stage: Stage = Stage.GREETING
    history: List[Message] = []

class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    user_message: Optional[str] = None

class ChatResponse(BaseModel):
    session_id: str
    stage: Stage
    agent_message: str

class BriefRequest(BaseModel):
    session_id: str

class ClinicalBrief(BaseModel):
    chief_complaint: str = Field(description="The primary reason for the patient's visit")
    hpi: str = Field(description="History of Present Illness")
    ros: str = Field(description="Review of Systems")

# In-memory storage for simplicity (use a database in production)
sessions: Dict[str, SessionData] = {}

SYSTEM_PROMPT = """You are a Clinical Intake Agent. Your goal is to systematically collect patient information.
You must guide the conversation through the following stages:
1. GREETING: Briefly greet the patient and ask how you can help them today.
2. CHIEF_COMPLAINT: Identify the main reason for the visit.
3. HPI (History of Present Illness): Ask specific questions to expand on the chief complaint (e.g., onset, location, duration, character, aggravating/alleviating factors, radiation, timing, severity).
4. FOCUSED_ROS (Review of Systems): Ask about related symptoms.
5. CLARIFICATION: Ask any final clarifying questions if needed.
6. COMPLETE: Tell the patient you have all the necessary information and end the intake gracefully.

Current Stage: {current_stage}

IMPORTANT: You MUST respond EXCLUSIVELY in valid JSON format with exactly two keys:
- "agent_message": Your conversational response to the patient.
- "next_stage": The stage we should transition to after your message. Must be one of: GREETING, CHIEF_COMPLAINT, HPI, FOCUSED_ROS, CLARIFICATION, COMPLETE.

Rules:
- Ask only 1-2 questions at a time.
- Be empathetic, concise, and professional.
- Move to the next stage when you have gathered sufficient information for the current stage.
- Do NOT output any conversational text OUTSIDE of the JSON object.
- If you cannot generate valid JSON, just output the JSON object structure anyway.
- Do NOT output any markdown blocks (like ```json), just output the raw JSON object.
"""

def get_llm_response(messages: list):
    provider = os.getenv("LLM_PROVIDER", "openrouter").lower()
    logger.debug(f"Using provider: {provider}")
    
    if provider == "cerebras":
        from cerebras.cloud.sdk import Cerebras
        client = Cerebras(api_key=os.getenv("CEREBRAS_API_KEY"))
        model = os.getenv("CEREBRAS_MODEL", "llama3.1-8b")
        
        response = client.chat.completions.create(
            messages=messages,
            model=model,
            max_completion_tokens=1000,
            temperature=0.1,
            stream=False
        )
        return response.choices[0].message.content
        
    elif provider == "openrouter":
        model = os.getenv("OPENROUTER_MODEL", "openrouter/auto")
        api_base = os.getenv("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")
        app_name = os.getenv("OR_APP_NAME", "Intake Agent")
        site_url = os.getenv("OR_SITE_URL", "http://localhost:8080")
        
        if not model.startswith("openrouter/"):
            model = f"openrouter/{model}"
            
        resp = completion(
            model=model,
            api_base=api_base,
            headers={
                "HTTP-Referer": site_url,
                "X-Title": app_name
            },
            messages=messages,
            max_tokens=1000,
            temperature=0.1
        )
        return resp.choices[0].message.content
        
    elif provider == "gemini":
        model = os.getenv("GEMINI_MODEL", "gemini/gemini-pro")
        resp = completion(
            model=model,
            messages=messages,
            max_tokens=1000,
            temperature=0.1
        )
        return resp.choices[0].message.content
        
    else:
        raise ValueError(f"Unsupported provider: {provider}")

def parse_json_from_llm(content: str, fallback_stage: str = "COMPLETE"):
    logger.debug(f"Raw LLM Content for parsing: {content}")
    # Try to find JSON block with regex
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        clean_content = match.group(0)
    else:
        clean_content = content.strip()
        
    try:
        return json.loads(clean_content)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON Parse Error: {e} - Content: {content}. Attempting heuristic recovery.")
        # If it's not JSON, assume the whole content is the message
        return {
            "agent_message": content.strip(),
            "next_stage": fallback_stage
        }

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    
    if session_id not in sessions:
        sessions[session_id] = SessionData(session_id=session_id)
        
    session = sessions[session_id]
    
    # Append user message if provided
    if request.user_message:
        session.history.append(Message(role="user", content=request.user_message))
    
    # Prepare messages for LLM
    llm_messages = [{"role": "system", "content": SYSTEM_PROMPT.format(current_stage=session.stage.value)}]
    for msg in session.history:
        llm_messages.append({"role": msg.role, "content": msg.content})
        
    try:
        content = get_llm_response(llm_messages)
        logger.info(f"LLM Response: {content}")
        
        parsed = parse_json_from_llm(content, fallback_stage=session.stage.value)
        agent_message = parsed.get("agent_message", "I apologize, I didn't quite catch that.")
        next_stage_str = parsed.get("next_stage", session.stage.value)
        
        # Validate next stage
        try:
            next_stage = Stage(next_stage_str)
        except ValueError:
            logger.warning(f"Invalid stage received from LLM: {next_stage_str}")
            next_stage = session.stage
            
        # Update session
        session.stage = next_stage
        session.history.append(Message(role="assistant", content=agent_message))
        
        return ChatResponse(
            session_id=session.session_id,
            stage=session.stage,
            agent_message=agent_message
        )
        
    except Exception as e:
        logger.error(f"Error in /chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

BRIEF_PROMPT = """You are a medical assistant. Review the following patient intake conversation and summarize it into a structured Clinical Brief.
Extract the Chief Complaint, History of Present Illness (HPI), and Review of Systems (ROS).

IMPORTANT: You MUST respond EXCLUSIVELY in valid JSON format with exactly three keys:
- "chief_complaint": A concise statement of the primary reason for the visit.
- "hpi": A detailed summary of the history of present illness.
- "ros": A summary of the review of systems mentioned.

Do NOT output any conversational text OUTSIDE of the JSON object.
Do NOT output any markdown blocks, just the raw JSON object.
"""

@app.post("/brief", response_model=ClinicalBrief)
async def generate_brief(request: BriefRequest):
    if request.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session = sessions[request.session_id]
    
    if session.stage != Stage.COMPLETE:
        # For debug, we'll allow generating brief even if not complete if requested
        pass
        
    llm_messages = [{"role": "system", "content": BRIEF_PROMPT}]
    for msg in session.history:
        llm_messages.append({"role": msg.role, "content": msg.content})
        
    try:
        content = get_llm_response(llm_messages)
        logger.info(f"Brief Generation Response: {content}")
        
        parsed = parse_json_from_llm(content, fallback_stage="COMPLETE")
        return ClinicalBrief(
            chief_complaint=parsed.get("chief_complaint", "Not available"),
            hpi=parsed.get("hpi", "Not available"),
            ros=parsed.get("ros", "Not available")
        )
        
    except Exception as e:
        logger.error(f"Error in /brief: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
