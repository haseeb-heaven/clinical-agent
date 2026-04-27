import os
import json
import uuid
import logging
import re
from enum import Enum
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from openai import OpenAI
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

# In-memory storage — sessions are lost on server restart.
sessions: Dict[str, SessionData] = {}

SYSTEM_PROMPT = """You are a Clinical Intake Agent and your name is "Clinical Agent". You are conducting a structured patient intake interview.
Your goal is to systematically collect clinical information using the OLDCARTS framework and a focused Review of Systems.

Guide the conversation through these stages:
1. GREETING: Warmly greet the patient and ask how you can help them today.
2. CHIEF_COMPLAINT: Identify and confirm the primary reason for the visit in the patient's own words.
3. HPI: Systematically explore the chief complaint using OLDCARTS:
   - Onset: When did it start? Did it come on suddenly or gradually?
   - Location: Where exactly is the symptom? Does it radiate anywhere?
   - Duration: How long does it last? Is it constant or intermittent?
   - Character: How would you describe it? (sharp, dull, burning, throbbing, pressure, etc.)
   - Aggravating factors: What makes it worse? (movement, food, stress, position, etc.)
   - Relieving factors: What makes it better? (rest, medication, ice, heat, etc.)
   - Timing: When does it occur? Any pattern? (morning, after meals, at night, etc.)
   - Severity: On a scale of 1-10, how would you rate it?
4. FOCUSED_ROS: Ask about associated symptoms relevant to the chief complaint. Always screen:
   - Constitutional: Fever, chills, fatigue, weight changes, night sweats
   - Cardiovascular: Chest pain, palpitations, shortness of breath, leg swelling
   - Respiratory: Cough, wheezing, difficulty breathing
   - GI: Nausea, vomiting, diarrhea, constipation, appetite changes
   - Neurological: Headache, dizziness, numbness, tingling, vision changes
   - Musculoskeletal: Joint pain or stiffness, muscle weakness
5. CLARIFICATION: Ask any final questions — current medications, allergies, or relevant medical history.
6. COMPLETE: Confirm you have all needed information and close the intake warmly.

Current Stage: {current_stage}

IMPORTANT: You MUST respond EXCLUSIVELY in valid JSON format with exactly two keys:
- "agent_message": Your conversational response to the patient. Be empathetic and professional.
- "next_stage": The stage to transition to. Must be one of: GREETING, CHIEF_COMPLAINT, HPI, FOCUSED_ROS, CLARIFICATION, COMPLETE.

Rules:
- Ask only 1-2 questions at a time — do NOT dump all OLDCARTS questions at once.
- Be empathetic, concise, and professional.
- Move to the next stage only when you have gathered sufficient information for the current stage.
- Do NOT output any text OUTSIDE the JSON object.
- Do NOT output markdown blocks (like ```json), just raw JSON.
"""

def build_openrouter_client() -> OpenAI:
    """Build an OpenAI-compatible client pointed at OpenRouter."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not set in .env")
    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": os.getenv("OR_SITE_URL", "http://localhost:8080"),
            "X-Title": os.getenv("OR_APP_NAME", "Clinical Intake Agent"),
        }
    )

def build_cerebras_client():
    """Build Cerebras native client."""
    from cerebras.cloud.sdk import Cerebras
    return Cerebras(api_key=os.getenv("CEREBRAS_API_KEY"))

def get_llm_response(messages: list) -> str:
    provider = os.getenv("LLM_PROVIDER", "openrouter").lower()
    logger.debug(f"Using provider: {provider}")

    if provider == "cerebras":
        client = build_cerebras_client()
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
        client = build_openrouter_client()
        # Model name must NOT have an "openrouter/" prefix — use the raw model ID
        model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")
        # Strip accidental prefix if someone added it in .env
        if model.startswith("openrouter/"):
            model = model[len("openrouter/"):]
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=1000,
            temperature=0.1,
        )
        return resp.choices[0].message.content

    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}. Choose 'cerebras' or 'openrouter'.")

def parse_json_from_llm(content: str, fallback_stage: str = "COMPLETE"):
    logger.debug(f"Raw LLM Content for parsing: {content}")
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        clean_content = match.group(0)
    else:
        clean_content = content.strip()

    try:
        return json.loads(clean_content)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON Parse Error: {e} — Content: {content}. Falling back to raw text.")
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

    if request.user_message:
        session.history.append(Message(role="user", content=request.user_message))

    llm_messages = [{"role": "system", "content": SYSTEM_PROMPT.format(current_stage=session.stage.value)}]
    for msg in session.history:
        llm_messages.append({"role": msg.role, "content": msg.content})

    try:
        content = get_llm_response(llm_messages)
        logger.info(f"LLM Response: {content}")

        parsed = parse_json_from_llm(content, fallback_stage=session.stage.value)
        agent_message = parsed.get("agent_message", "I apologize, I didn't quite catch that.")
        next_stage_str = parsed.get("next_stage", session.stage.value)

        try:
            next_stage = Stage(next_stage_str)
        except ValueError:
            logger.warning(f"Invalid stage from LLM: {next_stage_str}")
            next_stage = session.stage

        session.stage = next_stage
        session.history.append(Message(role="assistant", content=agent_message))

        return ChatResponse(
            session_id=session.session_id,
            stage=session.stage,
            agent_message=agent_message
        )

    except Exception as e:
        logger.error(f"Error in /chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

BRIEF_PROMPT = """You are a medical scribe. Review the patient intake conversation below and generate a structured Clinical Brief.

IMPORTANT: Respond EXCLUSIVELY in valid JSON with exactly three keys:
- "chief_complaint": A concise single-sentence statement of the primary reason for the visit.
- "hpi": A detailed paragraph-style summary of the History of Present Illness using OLDCARTS elements.
- "ros": A system-by-system summary of positive and notable negative findings from the Review of Systems.

Do NOT include any text outside the JSON. Do NOT use markdown code blocks.
"""

@app.post("/brief", response_model=ClinicalBrief)
async def generate_brief(request: BriefRequest):
    if request.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[request.session_id]

    llm_messages = [{"role": "system", "content": BRIEF_PROMPT}]
    for msg in session.history:
        llm_messages.append({"role": msg.role, "content": msg.content})

    try:
        content = get_llm_response(llm_messages)
        logger.info(f"Brief Generation Response: {content}")

        parsed = parse_json_from_llm(content, fallback_stage="COMPLETE")

        # LLM may return `ros` as a structured dict — convert to readable string
        ros_raw = parsed.get("ros", "Not available")
        if isinstance(ros_raw, dict):
            ros_str = "\n".join(f"{k}: {v}" for k, v in ros_raw.items())
        else:
            ros_str = str(ros_raw)

        return ClinicalBrief(
            chief_complaint=parsed.get("chief_complaint", "Not available"),
            hpi=parsed.get("hpi", "Not available"),
            ros=ros_str
        )

    except Exception as e:
        logger.error(f"Error in /brief: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/session/{session_id}")
async def reset_session(session_id: str):
    """Delete a session so the frontend can start fresh without a server restart."""
    sessions.pop(session_id, None)
    return {"status": "ok", "session_id": session_id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
