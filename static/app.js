const form = document.getElementById('analyze-form');
const statusBox = document.getElementById('status');
const resultCard = document.getElementById('results');
const topWordsList = document.getElementById('top-words');

const videoIdEl = document.getElementById('video-id');
const totalWordsEl = document.getElementById('total-words');
const uniqueWordsEl = document.getElementById('unique-words');
const subtitleLanguageEl = document.getElementById('subtitle-language');
const subtitleSourceEl = document.getElementById('subtitle-source');

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
