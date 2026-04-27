import pytest
import json
from main import parse_json_from_llm, Stage

def test_parse_json_from_llm_valid():
    content = '{"agent_message": "Hello", "next_stage": "CHIEF_COMPLAINT"}'
    result = parse_json_from_llm(content)
    assert result["agent_message"] == "Hello"
    assert result["next_stage"] == "CHIEF_COMPLAINT"

def test_parse_json_from_llm_with_markdown():
    content = '```json\n{"agent_message": "Hi", "next_stage": "HPI"}\n```'
    result = parse_json_from_llm(content)
    assert result["agent_message"] == "Hi"
    assert result["next_stage"] == "HPI"

def test_parse_json_from_llm_invalid_fallback():
    content = "Not a JSON at all"
    result = parse_json_from_llm(content, fallback_stage="GREETING")
    assert result["agent_message"] == "Not a JSON at all"
    assert result["next_stage"] == "GREETING"

def test_parse_json_from_llm_partial_json():
    content = 'Some text before {"agent_message": "Found it", "next_stage": "COMPLETE"} and after'
    result = parse_json_from_llm(content)
    assert result["agent_message"] == "Found it"
    assert result["next_stage"] == "COMPLETE"

def test_stage_enum_values():
    assert Stage.GREETING == "GREETING"
    assert Stage.COMPLETE == "COMPLETE"
