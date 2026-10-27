(() => {
const $ = (id) => document.getElementById(id);
const api = window.imageLibrary;
const bridgeMethods = ['status', 'photos', 'index', 'search', 'openSource', 'onIndexProgress'];
let allPhotos = [];
let status;
let busy = false;
let selected;
let activeMediaType = 'all';
let currentQuery = '';

function notice(message = '', error = false) {
  $('notice').textContent = message.replace(/^Error invoking remote method '[^']+': (?:Error: )?/, '');
  $('notice').hidden = !message;
  $('notice').classList.toggle('error', error);
}

function setBusy(value) {
  busy = value;
  $('search-form').classList.toggle('busy', value);
  $('search-button').disabled = value || !status?.indexed;
  $('index-button').disabled = value || !status?.total || !status?.has_key;
  $('refresh-button').disabled = value;
  $('reset-button').disabled = value;
  document.querySelectorAll('[data-query]').forEach((button) => { button.disabled = value || !status?.indexed; });
  document.querySelectorAll('[data-media-type]').forEach((button) => { button.disabled = value || !status?.total; });
  $('gallery').setAttribute('aria-busy', String(value));
}

function updateStatus(value) {
  status = value;
  $('connection').textContent = `${value.indexed} / ${value.total} 张已就绪`;
  $('connection').classList.toggle('ready', value.indexed > 0);
  $('index-button').textContent = value.total && value.indexed === value.total ? '检查索引' : '建立索引';
  $('footer-info').textContent = `${value.model}${value.dimension ? ` · ${value.dimension} 维` : ''} · 图片向量保存在本地`;
  setBusy(busy);
}

function render(photos, isSearch = false) {
  const fragment = document.createDocumentFragment();
  photos.forEach((photo, index) => {
    const card = document.createElement('button');
    card.className = 'photo-card';
    card.dataset.id = photo.id;
    card.setAttribute('aria-label', `查看${photo.title}`);
    const cover = document.createElement('div');
    cover.className = 'photo-cover';
    const image = document.createElement('img');
    image.src = `imagerag://photos/${photo.id}?thumb=1`;
    image.alt = photo.title;
    image.loading = index < 12 ? 'eager' : 'lazy';
    cover.append(image);
    if (isSearch) {
      const rank = document.createElement('span');
      rank.className = 'photo-rank';
      rank.textContent = String(index + 1).padStart(2, '0');
      cover.append(rank);
    }
    const info = document.createElement('div');
    info.className = 'photo-description';
    const text = document.createElement('div');
    const title = document.createElement('div');
    title.className = 'photo-title';
    title.textContent = photo.title;
    const meta = document.createElement('div');
    meta.className = 'photo-meta';
    meta.textContent = `${photo.width} × ${photo.height} · ${photo.dataset}`;
    text.append(title, meta);
    info.append(text);
    if (isSearch) {
      const score = document.createElement('span');
      score.className = 'photo-score';
      score.textContent = photo.score.toFixed(3);
      score.title = '余弦相似度，不是匹配概率';
      info.append(score);
    }
    card.append(cover, info);
    card.addEventListener('click', () => showPhoto(photo));
    fragment.append(card);
  });
  $('gallery').replaceChildren(fragment);
  $('empty-state').hidden = photos.length > 0;
  $('reset-button').hidden = !isSearch;
}

function showAll() {
  currentQuery = '';
  const names = { all: '全部图片', photo: '生活照片', screenshot: '屏幕截图', illustration: '卡通 / 插画' };
  $('gallery-title').textContent = names[activeMediaType];
  const types = status?.media_types || {};
  $('gallery-info').textContent = `${allPhotos.length} 张图片 · 生活照片 ${types.photo || 0} · 屏幕截图 ${types.screenshot || 0} · 卡通/插画 ${types.illustration || 0}`;
  document.querySelectorAll('[data-media-type]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.mediaType === activeMediaType)));
  render(allPhotos.filter((photo) => activeMediaType === 'all' || (photo.media_type || 'photo') === activeMediaType));
}

async function refresh() {
  try {
    const [value, photos] = await Promise.all([api.status(), api.photos()]);
    updateStatus(value);
    allPhotos = photos;
    showAll();
    if (!value.has_key) notice('尚未配置 API Key。请在项目 .env 中填写后重启应用。');
    else if (value.total && value.indexed < value.total) notice('测试图库已准备好。点击「建立索引」，为图片生成向量后即可搜索。');
    else notice();
  } catch (error) { notice(error.message, true); }
  finally { setBusy(false); }
}

async function search(query) {
  if (busy || !query.trim()) return;
  document.querySelectorAll('[data-media-type]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.mediaType === activeMediaType)));
  $('query').value = query;
  notice();
  setBusy(true);
  document.querySelector('.search-label').textContent = '正在寻找';
  try {
    const result = await api.search(query, activeMediaType);
    currentQuery = result.query;
    $('gallery-title').textContent = `“${result.query}”`;
    const usageText = result.api_called ? 'AI 语义检索' : '命中本地缓存 · 本次未调用模型';
    $('gallery-info').textContent = `从 ${result.searched} 张图片中找到最相关的 ${result.results.length} 张 · ${(result.elapsed_ms / 1000).toFixed(2)} 秒 · ${usageText}`;
    render(result.results, true);
    updateStatus(await api.status());
  } catch (error) { notice(error.message, true); }
  finally {
    document.querySelector('.search-label').textContent = '搜索图片';
    setBusy(false);
  }
}

function showPhoto(photo) {
  selected = photo;
  $('detail-image').src = `imagerag://photos/${photo.id}`;
  $('detail-image').alt = photo.title;
  $('photo-title').textContent = photo.title;
  $('photo-meta').textContent = `${photo.width} × ${photo.height}${photo.score !== undefined ? ` · 语义相似度 ${photo.score.toFixed(4)}` : ''}`;
  $('photo-credit').textContent = `摄影：${photo.author || '见来源页'} · 许可：${photo.license} · Open Images validation`;
  $('photo-dialog').showModal();
}

// A browser/file preview cannot load Electron's preload or private Python bridge.
// Stop before registering any action that would dereference a missing API.
if (!api || !bridgeMethods.every((method) => typeof api[method] === 'function')) {
  setBusy(false);
  $('query').disabled = true;
  $('refresh-button').disabled = true;
  $('reset-button').disabled = true;
  $('connection').textContent = '请使用桌面应用';
  $('gallery').setAttribute('aria-busy', 'false');
  $('gallery-info').textContent = '当前页面未连接桌面图库。';
  $('footer-info').textContent = '需要通过 Electron 启动';
  notice('请通过桌面应用使用搜图功能。\n在项目终端运行：\nnpm start\n如果桌面应用也出现此提示，请关闭后重新启动。', true);
  $('search-form').addEventListener('submit', (event) => event.preventDefault());
  return;
}

$('search-form').addEventListener('submit', (event) => { event.preventDefault(); search($('query').value); });
document.querySelectorAll('[data-query]').forEach((button) => button.addEventListener('click', () => search(button.dataset.query)));
document.querySelectorAll('[data-media-type]').forEach((button) => button.addEventListener('click', () => { activeMediaType = button.dataset.mediaType; notice(); if (currentQuery) search(currentQuery); else showAll(); }));
$('reset-button').addEventListener('click', () => { activeMediaType = 'all'; notice(); showAll(); });
$('refresh-button').addEventListener('click', refresh);
$('close-dialog').addEventListener('click', () => $('photo-dialog').close());
$('photo-dialog').addEventListener('click', (event) => { if (event.target === $('photo-dialog')) $('photo-dialog').close(); });
$('source-button').addEventListener('click', async () => {
  try { await api.openSource(selected.id); }
  catch (error) { $('photo-dialog').close(); notice(error.message, true); }
});
api.onIndexProgress(({ done, total }) => {
  $('index-progress').hidden = false;
  $('progress-bar').max = total;
  $('progress-bar').value = done;
  $('progress-label').textContent = `图片入库 ${done} / ${total}`;
});
$('index-button').addEventListener('click', async () => {
  if (busy) return;
  setBusy(true);
  notice('正在为图片建立索引，完成后会保存在本地。');
  try {
    updateStatus(await api.index());
    notice();
  } catch (error) { notice(error.message, true); }
  finally { $('index-progress').hidden = true; setBusy(false); }
});
refresh();
})();
