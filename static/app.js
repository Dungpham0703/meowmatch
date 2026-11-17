'use strict';
const $ = id => document.getElementById(id);
const methods = ['keyword', 'image'];
const labels = {keyword: 'Keyword Search', image: 'Image Semantic Search'};
let current = null;
let requestNumber = 0;
let controller = null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function state(kind, title, description, retry = false) {
  const box = el('div', 'empty-state');
  box.append(el('strong', '', title), el('p', '', description));
  if (retry) {
    const button = el('button', 'retry-button', 'Try again ↗');
    button.type = 'button';
    button.addEventListener('click', () => $('search-form').requestSubmit());
    box.append(button);
  }
  $(`list-${kind}`).replaceChildren(box);
}
function loading() {
  $('results').setAttribute('aria-busy', 'true');
  methods.forEach(kind => {
    const items = [0, 1].map((_, index) => {
      const card = el('div', 'skeleton-card');
      card.setAttribute('aria-hidden', 'true');
      card.append(el('div', 'skeleton-image', index ? '' : 'Finding your kind of cat…'), el('div', 'skeleton-line'));
      return card;
    });
    $(`list-${kind}`).replaceChildren(...items);
    $(`meta-${kind}`).textContent = 'SEARCHING…';
  });
}
function card(item, index) {
  const button = el('button', 'meme-card');
  button.type = 'button';
  button.dataset.id = item.id;
  button.setAttribute('aria-label', `Rank ${index + 1}: ${item.name}. View meme`);
  const imageWrap = el('span', 'meme-image-wrap');
  const img = el('img');
  img.src = item.image;
  img.alt = item.name;
  img.width = 360; img.height = 280;
  img.loading = index < 2 ? 'eager' : 'lazy';
  imageWrap.append(img, el('span', 'rank', String(index + 1).padStart(2, '0')));
  const bottom = el('span', 'meme-bottom');
  bottom.append(el('span', '', item.tags.slice(0, 2).join(' / ')), el('span', '', '↗'));
  button.append(imageWrap, el('span', 'meme-name', item.name), el('span', 'meme-caption', item.caption), bottom);
  button.addEventListener('click', () => openDetail(item));
  return button;
}
function render(data) {
  current = data;
  $('query-summary').textContent = `Results for “${data.query}”`;
  methods.forEach(kind => {
    const group = data.methods[kind];
    if (group.status !== 'ok') {
      $(`meta-${kind}`).textContent = 'UNAVAILABLE';
      state(kind, 'Search is temporarily unavailable', group.error, true);
      return;
    }
    $(`meta-${kind}`).textContent = `${group.results.length} RESULTS · ${group.retrieval_ms.toFixed(0)} MS RETRIEVAL`;
    if (!group.results.length) {
      state(kind, 'No matching cats yet', kind === 'keyword' ? 'No words matched. Try a shorter query, or try Image Semantic Search.' : 'Try describing your mood in a different way.');
      return;
    }
    $(`list-${kind}`).replaceChildren(...group.results.map(card));
  });
  $('technical-content').textContent = `${data.model} · ${data.dimensions} dimensions · Both methods search the same collection. Query embedding: ${data.embedding_ms.toFixed(0)} ms${data.query_cache_hit ? ' (cached)' : ''}, compared directly with image embeddings. Column timings measure database retrieval only. Keyword search uses full-text rank; image semantic search uses cosine similarity. Scores are not accuracy percentages. This collection uses exact vector retrieval in pgvector.`;
}
async function search(event) {
  event?.preventDefault();
  const query = $('query').value.trim();
  if (!query) { $('query').focus(); return; }
  const number = ++requestNumber;
  controller?.abort(); controller = new AbortController();
  $('form-error').hidden = true;
  $('query-summary').textContent = `Searching for “${query}”…`;
  $('search-button').querySelector('span').textContent = 'Searching…';
  loading();
  try {
    const response = await fetch('/api/search/compare', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({query, top_k: Number($('top-k').value)}), signal: controller.signal
    });
    if (!response.ok) throw new Error(response.status === 503 ? 'The database is unavailable. Please try again shortly.' : 'Could not load results. Please try again.');
    const data = await response.json();
    if (number !== requestNumber) return;
    render(data);
  } catch (error) {
    if (error.name === 'AbortError' || number !== requestNumber) return;
    current = null;
    $('form-error').textContent = error.message;
    $('form-error').hidden = false;
    $('query-summary').textContent = 'This search could not be completed.';
    methods.forEach(kind => { $(`meta-${kind}`).textContent = 'UNAVAILABLE'; state(kind, 'These cats are playing hide-and-seek', 'Check your connection and try searching again.', true); });
  } finally {
    if (number === requestNumber) {
      $('results').setAttribute('aria-busy', 'false');
      $('search-button').querySelector('span').textContent = 'Find memes';
    }
  }
}
function openDetail(item) {
  $('detail-name').textContent = item.name;
  $('detail-caption').textContent = item.caption;
  $('detail-image').src = item.image; $('detail-image').alt = item.name;
  $('original-link').href = item.image;
  $('detail-tags').replaceChildren(...item.tags.map(tag => el('span', '', tag)));
  $('detail-ranks').replaceChildren(...methods.map(kind => {
    const group = current.methods[kind];
    const index = group.results.findIndex(result => result.id === item.id);
    const row = el('div', 'rank-row');
    const score = index >= 0 ? group.results[index].score.toFixed(4) : '';
    row.append(el('span', '', labels[kind]), el('span', '', index >= 0 ? `#${index + 1} · ${score} ${kind === 'keyword' ? 'rank' : 'cosine'}` : group.status !== 'ok' ? 'Unavailable' : `Outside top ${current.top_k}`));
    return row;
  }));
  document.querySelectorAll('.meme-card').forEach(node => node.classList.toggle('is-selected', node.dataset.id === item.id));
  $('detail-dialog').showModal();
}
function activateTab(kind) {
  document.querySelectorAll('[data-method]').forEach(button => {
    const active = button.dataset.method === kind;
    button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1;
  });
  methods.forEach(method => $(`panel-${method}`).classList.toggle('is-active', method === kind));
}
$('search-form').addEventListener('submit', search);
$('top-k').addEventListener('change', () => $('search-form').requestSubmit());
document.querySelectorAll('[data-query]').forEach(button => button.addEventListener('click', () => {
  $('query').value = button.dataset.query; $('search-form').requestSubmit();
}));
document.querySelectorAll('[data-method]').forEach(button => {
  button.addEventListener('click', () => activateTab(button.dataset.method));
  button.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    let index = methods.indexOf(button.dataset.method);
    index = event.key === 'Home' ? 0 : event.key === 'End' ? methods.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : methods.length - 1)) % methods.length;
    activateTab(methods[index]); $(`tab-${methods[index]}`).focus();
  });
});
$('about-button').addEventListener('click', () => $('about-dialog').showModal());
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => $(button.dataset.close).close()));
document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => {
  const rect = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
}));
async function init() {
  try {
    const response = await fetch('/api/health');
    if (!response.ok) throw new Error();
    const health = await response.json();
    $('collection-count').textContent = `${health.sticker_count} CAT MEMES`;
    if (!health.ready) {
      methods.forEach(kind => state(kind, 'The meme collection is being prepared', 'The collection is not ready yet. Please try again shortly.'));
      return;
    }
    await search();
  } catch {
    $('collection-count').textContent = 'DISCONNECTED';
    methods.forEach(kind => state(kind, 'Could not connect', 'Refresh the page or try searching again shortly.', true));
  }
}
init();
