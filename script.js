vkBridge.send('VKWebAppInit');

let USER_ID = null;
let currentFileUrl = null; // Добавили переменную для хранения ссылки на фото
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
async function initApp() {
    try {
        const data = await vkBridge.send('VKWebAppGetUserInfo');
        USER_ID = data.id;
        console.log("ID загружен:", USER_ID);
        loadHistory();
    } catch (e) {
        console.error("Ошибка VK Bridge:", e);
        setTimeout(initApp, 1000); // Пробуем еще раз через секунду
    }
}
initApp();

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

const fileInput = document.getElementById('fileInput');
const attachBtn = document.getElementById('attachBtn');

attachBtn.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    appendMessage('ai', `⏳ Загружаю фото...`);

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('https://neuro-master.online/api/upload', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();
        
        if (result.success) {
            currentFileUrl = result.url;
            appendMessage('ai', `✅ Фото прикреплено. Теперь напиши, что с ним сделать!`);
        } else {
            appendMessage('ai', `❌ Ошибка загрузки файла.`);
        }
    } catch (e) {
        appendMessage('ai', `🌐 Ошибка сети при отправке файла.`);
    }
});

async function sendMessage() {
    const text = userInput.value.trim();
    if (!text && !currentFileUrl) return; 
    if (!USER_ID) { alert("Подождите, ваш VK ID еще не загрузился."); return; }

    appendMessage('user', text || "Разбери это изображение");
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
            body: JSON.stringify({ 
                user_id: USER_ID, 
                prompt: text || "Опиши фото", 
                model_type: modelSelector.value,
                attachments: currentFileUrl ? [currentFileUrl] : [] // ПЕРЕДАЕМ ФОТО СЮДА
            }) 
        });
        const result = await response.json();
        
        document.getElementById(loadingId).remove();
        currentFileUrl = null; // Сбрасываем фото после отправки

        if (result.success) {
            appendMessage('ai', result.response, true);
        } else {
            appendMessage('ai', '❌ Ошибка: ' + (result.error || 'Неизвестная ошибка'));
        }
    } catch (e) {
        if(document.getElementById(loadingId)) document.getElementById(loadingId).remove();
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
