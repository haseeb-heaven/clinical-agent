document.addEventListener('DOMContentLoaded', () => {
    // ─── UUID helper ──────────────────────────────────────────────────────────
    const generateUUID = () => {
        if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
            const r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    };

    // ─── State ────────────────────────────────────────────────────────────────
    let sessionId = generateUUID();
    let isComplete = false;
    let voiceEnabled = false;
    let isRecording = false;
    let recognition = null;
    let currentBrief = null;

    // ─── DOM refs ─────────────────────────────────────────────────────────────
    const chatWindow       = document.getElementById('chat-window');
    const userInput        = document.getElementById('user-input');
    const sendBtn          = document.getElementById('send-btn');
    const typingIndicator  = document.getElementById('typing-indicator');
    const briefSection     = document.getElementById('brief-section');
    const briefCC          = document.getElementById('brief-cc');
    const briefHPI         = document.getElementById('brief-hpi');
    const briefROS         = document.getElementById('brief-ros');
    const sessionDisplay   = document.getElementById('session-short');
    const newSessionBtn    = document.getElementById('new-session-btn');
    const voiceToggleBtn   = document.getElementById('voice-toggle-btn');
    const voiceLabel       = voiceToggleBtn.querySelector('.voice-label');
    const micBtn           = document.getElementById('mic-btn');
    const copyBriefBtn     = document.getElementById('copy-brief-btn');
    const downloadBriefBtn = document.getElementById('download-brief-btn');
    const stageSteps       = document.querySelectorAll('.stage-step');

    // ─── Session display ──────────────────────────────────────────────────────
    sessionDisplay.textContent = sessionId.slice(0, 8) + '…';

    // ─── Stage tracker ────────────────────────────────────────────────────────
    const STAGES = ['GREETING', 'CHIEF_COMPLAINT', 'HPI', 'FOCUSED_ROS', 'CLARIFICATION', 'COMPLETE'];

    function updateStageTracker(stage) {
        const currentIdx = STAGES.indexOf(stage);
        stageSteps.forEach((el, i) => {
            el.classList.remove('active', 'done');
            if (i < currentIdx) el.classList.add('done');
            else if (i === currentIdx) el.classList.add('active');
        });
    }

    // ─── Scroll helper ────────────────────────────────────────────────────────
    const scrollToBottom = () => chatWindow.scrollTop = chatWindow.scrollHeight;

    // ─── Append message ───────────────────────────────────────────────────────
    function appendMessage(sender, text) {
        const div = document.createElement('div');
        div.classList.add('message');
        if (sender === 'user')   div.classList.add('user-message');
        if (sender === 'agent')  div.classList.add('agent-message');
        if (sender === 'system') div.classList.add('system-message');
        div.textContent = text;
        chatWindow.appendChild(div);
        scrollToBottom();
        return div;
    }

    // ─── Typing indicator ─────────────────────────────────────────────────────
    const showTyping = () => {
        typingIndicator.classList.remove('hidden');
        sendBtn.disabled = true;
    };
    const hideTyping = () => {
        typingIndicator.classList.add('hidden');
        if (!isComplete) {
            sendBtn.disabled = false;
            userInput.focus();
        }
    };

    // ─── TTS ──────────────────────────────────────────────────────────────────
    function speak(text) {
        if (!voiceEnabled || !window.speechSynthesis) return;
        window.speechSynthesis.cancel();
        const utter = new SpeechSynthesisUtterance(text);
        utter.rate = 0.95;
        utter.pitch = 1.0;
        // Prefer a female English voice if available
        const voices = window.speechSynthesis.getVoices();
        const preferred = voices.find(v => v.lang.startsWith('en') && v.name.toLowerCase().includes('female'))
                       || voices.find(v => v.lang.startsWith('en'));
        if (preferred) utter.voice = preferred;
        window.speechSynthesis.speak(utter);
    }

    // ─── Voice toggle ─────────────────────────────────────────────────────────
    voiceToggleBtn.addEventListener('click', () => {
        voiceEnabled = !voiceEnabled;
        voiceLabel.textContent = voiceEnabled ? 'Voice On' : 'Voice Off';
        voiceToggleBtn.classList.toggle('voice-active', voiceEnabled);
        if (!voiceEnabled) window.speechSynthesis?.cancel();
    });

    // ─── Speech recognition (mic button) ─────────────────────────────────────
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'en-US';

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            userInput.value = transcript;
            stopRecording();
            sendMessage();
        };

        recognition.onerror = () => stopRecording();
        recognition.onend = () => stopRecording();

        micBtn.addEventListener('click', () => {
            if (isComplete) return;
            if (isRecording) {
                recognition.stop();
                stopRecording();
            } else {
                startRecording();
            }
        });
    } else {
        micBtn.title = 'Speech recognition not supported in this browser';
        micBtn.style.opacity = '0.4';
        micBtn.style.cursor = 'not-allowed';
    }

    function startRecording() {
        if (!recognition || isComplete) return;
        isRecording = true;
        micBtn.classList.add('recording');
        userInput.placeholder = 'Listening…';
        recognition.start();
    }

    function stopRecording() {
        isRecording = false;
        micBtn.classList.remove('recording');
        userInput.placeholder = 'Type your response here… or use the mic';
    }

    // ─── Brief generation ─────────────────────────────────────────────────────
    async function fetchBrief() {
        try {
            const res = await fetch('/brief', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId })
            });
            if (!res.ok) throw new Error('Brief request failed');
            const data = await res.json();
            currentBrief = data;

            briefCC.textContent  = data.chief_complaint;
            briefHPI.textContent = data.hpi;
            briefROS.textContent = data.ros;
            briefSection.classList.remove('hidden');
        } catch (err) {
            console.error(err);
            briefCC.textContent = briefHPI.textContent = briefROS.textContent = 'Error generating brief.';
            briefSection.classList.remove('hidden');
        }
    }

    // ─── Export brief ─────────────────────────────────────────────────────────
    function briefToText() {
        if (!currentBrief) return '';
        return [
            'CLINICAL BRIEF',
            '==============',
            '',
            'Chief Complaint (CC)',
            '--------------------',
            currentBrief.chief_complaint,
            '',
            'History of Present Illness (HPI)',
            '---------------------------------',
            currentBrief.hpi,
            '',
            'Review of Systems (ROS)',
            '-----------------------',
            currentBrief.ros,
            '',
            `Generated: ${new Date().toLocaleString()}`,
            `Session ID: ${sessionId}`,
        ].join('\n');
    }

    copyBriefBtn.addEventListener('click', async () => {
        const text = briefToText();
        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
            copyBriefBtn.textContent = '✓ Copied!';
            setTimeout(() => copyBriefBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy`, 2000);
        } catch { /* clipboard blocked */ }
    });

    downloadBriefBtn.addEventListener('click', () => {
        const text = briefToText();
        if (!text) return;
        const blob = new Blob([text], { type: 'text/plain' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `clinical-brief-${sessionId.slice(0, 8)}.txt`;
        a.click();
        URL.revokeObjectURL(a.href);
    });

    // ─── Send message ─────────────────────────────────────────────────────────
    async function sendMessage() {
        const text = userInput.value.trim();
        if (!text || isComplete) return;
        userInput.value = '';
        appendMessage('user', text);
        showTyping();

        try {
            const res = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_message: text, session_id: sessionId })
            });
            if (!res.ok) throw new Error('Chat API error');

            const data = await res.json();
            appendMessage('agent', data.agent_message);
            updateStageTracker(data.stage);
            speak(data.agent_message);

            if (data.stage === 'COMPLETE') {
                isComplete = true;
                userInput.disabled = true;
                sendBtn.disabled = true;
                userInput.placeholder = 'Intake complete.';
                appendMessage('system', '✓ Clinical intake complete — generating brief…');
                await fetchBrief();
            }
        } catch (err) {
            console.error(err);
            appendMessage('system', 'An error occurred while communicating with the agent. Please try again.');
        } finally {
            if (!isComplete) hideTyping();
            else typingIndicator.classList.add('hidden');
        }
    }

    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', e => { if (e.key === 'Enter') sendMessage(); });
    userInput.focus();

    // ─── New session ──────────────────────────────────────────────────────────
    async function resetSession() {
        // Tell server to drop the old session
        try {
            await fetch(`/session/${sessionId}`, { method: 'DELETE' });
        } catch { /* server may not have the session, that's OK */ }

        // Reset local state
        sessionId = generateUUID();
        isComplete = false;
        currentBrief = null;
        sessionDisplay.textContent = sessionId.slice(0, 8) + '…';

        // Reset UI
        chatWindow.innerHTML = `
            <div class="message system-message">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                New session started. The agent will greet you shortly.
            </div>`;
        briefSection.classList.add('hidden');
        briefCC.textContent = briefHPI.textContent = briefROS.textContent = 'Loading…';
        userInput.disabled = false;
        sendBtn.disabled = false;
        userInput.placeholder = 'Type your response here… or use the mic';
        updateStageTracker('GREETING');
        window.speechSynthesis?.cancel();

        // Restart intake
        startIntake();
    }

    newSessionBtn.addEventListener('click', resetSession);

    // ─── Initial greeting ─────────────────────────────────────────────────────
    async function startIntake() {
        showTyping();
        try {
            const res = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId })
            });
            if (!res.ok) throw new Error('Failed to start chat');
            const data = await res.json();
            appendMessage('agent', data.agent_message);
            updateStageTracker(data.stage);
            speak(data.agent_message);
        } catch (err) {
            console.error(err);
            appendMessage('system', 'Could not connect to the agent. Is the server running?');
        } finally {
            hideTyping();
        }
    }

    startIntake();
});