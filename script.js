vkBridge.send('VKWebAppInit');

let USER_ID = null;
const API_URL = 'https://neuro-master.online/api/my_personal_ai'; 

marked.setOptions({
    highlight: function(code, lang) {
        const language = hljs.getLanguage(lang) ? lang : 'plaintext';
        return hljs.highlight(code, { language }).value;
    }
});

const chatBox = document.getElementById('chat-box');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const clearChatBtn = document.getElementById('clearChatBtn');
const modelSelector = document.getElementById('modelSelector');

// Функция отрисовки сообщения
function appendMessage(sender, text, isMarkdown = false) {
    const div = document.createElement('div');
    div.className = `message ${sender}-message`;
    if (isMarkdown) {
        div.innerHTML = marked.parse(text);
    } else {
        div.textContent = text;
    }
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
}

// Загрузка истории при старте!
async function loadHistory() {
    try {
        const response = await fetch(`${API_URL}/history?user_id=${USER_ID}`);
        const result = await response.json();
        
        if (result.success && result.history.length > 0) {
            chatBox.innerHTML = ''; // Убираем дефолтное приветствие
            result.history.forEach(msg => {
                // Если от ассистента - рендерим Markdown, если от юзера - просто текст
                appendMessage(msg.role === 'user' ? 'user' : 'ai', msg.content, msg.role !== 'user');
            });
        }
    } catch (e) {
        console.error("Не удалось загрузить историю", e);
    }
}

// Инициализация
vkBridge.send('VKWebAppGetUserInfo')
    .then(data => { 
        USER_ID = data.id; 
        loadHistory(); // Как только узнали ID, грузим старые переписки!
    })
    .catch(console.error);

// Очистка базы данных (метелочка)
clearChatBtn.addEventListener('click', async () => {
    if (!USER_ID) return;
    chatBox.innerHTML = '<div class="message ai-message">Очищаю память... ⏳</div>';
    try {
        const response = await fetch(API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: USER_ID, prompt: "", clear_history: true }) 
        });
        const result = await response.json();
        chatBox.innerHTML = `<div class="message ai-message">${result.response}</div>`;
    } catch(e) {
        chatBox.innerHTML = '<div class="message ai-message">❌ Ошибка очистки.</div>';
    }
});

// Отправка сообщения
async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;
    if (!USER_ID) { alert("Подождите, ваш VK ID еще не загрузился."); return; }

    appendMessage('user', text);
    userInput.value = '';
    sendBtn.disabled = true;

    const loadingId = 'loading-' + Date.now();
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'message ai-message';
    loadingDiv.id = loadingId;
    loadingDiv.textContent = 'Думаю... ⏳';
    chatBox.appendChild(loadingDiv);
    chatBox.scrollTop = chatBox.scrollHeight;

    try {
        const response = await fetch(API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: USER_ID, prompt: text, model_type: modelSelector.value }) 
        });
        const result = await response.json();
        
        chatBox.removeChild(document.getElementById(loadingId));

        if (result.success) {
            appendMessage('ai', result.response, true);
        } else {
            appendMessage('ai', '❌ Ошибка: ' + (result.error || 'Неизвестная ошибка'));
        }
    } catch (e) {
        chatBox.removeChild(document.getElementById(loadingId));
        appendMessage('ai', '🌐 Ошибка сети.');
    } finally {
        sendBtn.disabled = false;
    }
}

sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keypress', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});
