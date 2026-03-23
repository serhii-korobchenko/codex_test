const form = document.getElementById('analyze-form');
const statusBox = document.getElementById('status');
const resultCard = document.getElementById('results');
const topWordsList = document.getElementById('top-words');
const topicSelect = document.getElementById('topic-select');
const topicVideos = document.getElementById('topic-videos');
const loadTopicBtn = document.getElementById('load-topic-videos');

const videoIdEl = document.getElementById('video-id');
const totalWordsEl = document.getElementById('total-words');
const uniqueWordsEl = document.getElementById('unique-words');
const subtitleLanguageEl = document.getElementById('subtitle-language');
const subtitleSourceEl = document.getElementById('subtitle-source');

async function loadTopics() {
  try {
    const response = await fetch('/topics');
    const data = await response.json();

    topicSelect.innerHTML = '';
    data.topics.forEach((topic) => {
      const option = document.createElement('option');
      option.value = topic.id;
      option.textContent = topic.label;
      topicSelect.appendChild(option);
    });
  } catch {
    statusBox.className = 'status error';
    statusBox.textContent = 'Не вдалося завантажити перелік тематик.';
  }
}

async function loadTopicVideos() {
  const topic = topicSelect.value;
  if (!topic) {
    return;
  }

  topicVideos.innerHTML = '';
  statusBox.className = 'status';
  statusBox.textContent = 'Завантажую операторський перелік відео...';

  try {
    const response = await fetch(`/topic-videos?topic=${encodeURIComponent(topic)}`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || 'Помилка при отриманні відео за тематикою');
    }

    if (!data.videos.length) {
      topicVideos.innerHTML = '<li>Наразі оператор не додав відео для цієї теми.</li>';
      statusBox.className = 'status error';
      statusBox.textContent = 'Підходящі відео не знайдені.';
      return;
    }

    data.videos.forEach((video) => {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'select-video-btn';
      btn.textContent = `${video.title} (${video.subtitleSource})`;
      btn.addEventListener('click', () => {
        document.getElementById('url').value = video.url;
        statusBox.className = 'status success';
        statusBox.textContent = `Обрано відео: ${video.title}`;
      });
      li.appendChild(btn);
      topicVideos.appendChild(li);
    });

    statusBox.className = 'status success';
    statusBox.textContent = 'Список готовий. Обери відео для аналізу.';
  } catch (error) {
    statusBox.className = 'status error';
    statusBox.textContent = error.message;
  }
}

loadTopicBtn.addEventListener('click', loadTopicVideos);

form.addEventListener('submit', async (event) => {
  event.preventDefault();

  const url = document.getElementById('url').value.trim();
  const submitBtn = form.querySelector('button[type="submit"]');

  statusBox.className = 'status';
  statusBox.textContent = 'Отримую субтитри та аналізую слова...';
  submitBtn.disabled = true;
  resultCard.classList.add('hidden');

  try {
    const response = await fetch('/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || 'Невідома помилка сервера');
    }

    videoIdEl.textContent = data.videoId;
    totalWordsEl.textContent = data.totalWords;
    uniqueWordsEl.textContent = data.uniqueWords;
    subtitleLanguageEl.textContent = data.subtitleLanguage || '-';
    subtitleSourceEl.textContent = data.subtitleSource || '-';

    topWordsList.innerHTML = '';
    data.topWords.forEach((item) => {
      const li = document.createElement('li');
      li.textContent = `${item.word} — ${item.count}`;
      topWordsList.appendChild(li);
    });

    resultCard.classList.remove('hidden');
    statusBox.className = 'status success';
    statusBox.textContent = 'Готово!';
  } catch (error) {
    statusBox.className = 'status error';
    statusBox.textContent = error.message;
  } finally {
    submitBtn.disabled = false;
  }
});

loadTopics();
