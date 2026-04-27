import pytest
from unittest.mock import patch, MagicMock
from main import get_llm_response

@patch("os.getenv")
def test_get_llm_response_unsupported_provider(mock_env):
    mock_env.return_value = "unknown_provider"
    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER: unknown_provider"):
        get_llm_response([])

@patch("os.getenv")
@patch("cerebras.cloud.sdk.Cerebras")
def test_get_llm_response_cerebras(mock_cerebras, mock_env):
    # Setup environment
    def getenv_side_effect(key, default=None):
        if key == "LLM_PROVIDER": return "cerebras"
        if key == "CEREBRAS_API_KEY": return "test_key"
        if key == "CEREBRAS_MODEL": return "test_model"
        return default
    mock_env.side_effect = getenv_side_effect
    
    # Mock Cerebras client
    mock_client = MagicMock()
    mock_cerebras.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Cerebras Response"
    mock_client.chat.completions.create.return_value = mock_response
    
    result = get_llm_response([{"role": "user", "content": "hi"}])
    assert result == "Cerebras Response"
    mock_client.chat.completions.create.assert_called_once()

@patch("os.getenv")
@patch("main.OpenAI")
def test_get_llm_response_openrouter(mock_openai, mock_env):
    # Setup environment
    def getenv_side_effect(key, default=None):
        if key == "LLM_PROVIDER": return "openrouter"
        if key == "OPENROUTER_API_KEY": return "test_key"
        if key == "OPENROUTER_MODEL": return "gpt-4"
        return default
    mock_env.side_effect = getenv_side_effect
    
    # Mock OpenAI client (used for OpenRouter)
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "OpenRouter Response"
    mock_client.chat.completions.create.return_value = mock_response
    
    result = get_llm_response([{"role": "user", "content": "hi"}])
    assert result == "OpenRouter Response"
    mock_client.chat.completions.create.assert_called_once()
