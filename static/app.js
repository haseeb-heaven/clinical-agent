document.addEventListener('DOMContentLoaded', () => {
    // Generate UUID
    const generateUUID = () => {
        if (typeof crypto !== 'undefined' && crypto.randomUUID) {
            return crypto.randomUUID();
        }
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    };

    const sessionId = generateUUID();
    const chatWindow = document.getElementById('chat-window');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const typingIndicator = document.getElementById('typing-indicator');
    const briefSection = document.getElementById('brief-section');
    
    // Brief Elements
    const briefCC = document.getElementById('brief-cc');
    const briefHPI = document.getElementById('brief-hpi');
    const briefROS = document.getElementById('brief-ros');

    let isComplete = false;

    const scrollToBottom = () => {
        chatWindow.scrollTop = chatWindow.scrollHeight;
    };

    const appendMessage = (sender, text) => {
        const msgDiv = document.createElement('div');
        msgDiv.classList.add('message');
        if (sender === 'user') {
            msgDiv.classList.add('user-message');
        } else if (sender === 'agent') {
            msgDiv.classList.add('agent-message');
        } else if (sender === 'system') {
            msgDiv.classList.add('system-message');
        }
        msgDiv.textContent = text;
        chatWindow.appendChild(msgDiv);
        scrollToBottom();
    };

    const showTyping = () => {
        typingIndicator.classList.remove('hidden');
        sendBtn.disabled = true;
    };

    const hideTyping = () => {
        typingIndicator.classList.add('hidden');
        sendBtn.disabled = false;
        if (!isComplete) {
            userInput.focus();
        }
    };

    const fetchBrief = async () => {
        try {
            const response = await fetch('/brief', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId })
            });

            if (!response.ok) {
                throw new Error('Failed to fetch brief');
            }

            const data = await response.json();
            
            // Populate and show brief section
            briefCC.textContent = data.chief_complaint;
            briefHPI.textContent = data.hpi;
            briefROS.textContent = data.ros;
            
            briefSection.classList.remove('hidden');
        } catch (error) {
            console.error('Error fetching brief:', error);
            briefCC.textContent = 'Error loading brief.';
            briefHPI.textContent = 'Error loading brief.';
            briefROS.textContent = 'Error loading brief.';
            briefSection.classList.remove('hidden');
        }
    };

    const sendMessage = async () => {
        const text = userInput.value.trim();
        if (!text || isComplete) return;

        // Clear input
        userInput.value = '';
        
        // Add user message
        appendMessage('user', text);
        
        showTyping();

        try {
            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_message: text, session_id: sessionId })
            });

            if (!response.ok) {
                throw new Error('Chat API returned an error');
            }

            const data = await response.json();
            
            // Add agent message
            appendMessage('agent', data.agent_message);
            
            // Check if intake is complete
            if (data.stage === 'COMPLETE') {
                isComplete = true;
                userInput.disabled = true;
                sendBtn.disabled = true;
                userInput.placeholder = "Intake complete.";
                
                appendMessage('system', 'Clinical intake is complete. Generating brief...');
                
                // Fetch the clinical brief
                await fetchBrief();
            }
        } catch (error) {
            console.error('Error in chat:', error);
            appendMessage('system', 'An error occurred while communicating with the agent.');
        } finally {
            if (!isComplete) {
                hideTyping();
            } else {
                typingIndicator.classList.add('hidden');
            }
        }
    };

    // Event Listeners
    sendBtn.addEventListener('click', sendMessage);
    
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });

    // Focus input on load
    userInput.focus();
    
    // Initial greeting from agent
    const startIntake = async () => {
        showTyping();
        try {
            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId })
            });

            if (!response.ok) {
                throw new Error('Failed to start chat');
            }

            const data = await response.json();
            appendMessage('agent', data.agent_message);
        } catch (error) {
            console.error('Error starting chat:', error);
            appendMessage('system', 'An error occurred while connecting to the agent.');
        } finally {
            hideTyping();
        }
    };

    startIntake();
});