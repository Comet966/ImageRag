const { app, BrowserWindow, ipcMain, protocol, shell, session } = require('electron');
const { spawn } = require('node:child_process');
const { createInterface } = require('node:readline');
const fs = require('node:fs/promises');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const RUNTIME = path.join(ROOT, '.runtime');
const APP_URL = 'imagerag://app/index.html';
app.setPath('userData', path.join(RUNTIME, process.env.IMAGERAG_E2E === '1' ? 'electron-e2e' : 'electron'));
app.setPath('crashDumps', path.join(RUNTIME, 'crashes'));
app.setAppLogsPath(path.join(RUNTIME, 'logs'));
protocol.registerSchemesAsPrivileged([
  { scheme: 'imagerag', privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);

let window;
let worker;
let workerReady;
let sequence = 0;
let quitting = false;
const pending = new Map();

function startWorker() {
  const python = process.platform === 'win32'
    ? path.join(ROOT, '.venv', 'Scripts', 'python.exe')
    : path.join(ROOT, '.venv', 'bin', 'python');
  workerReady = new Promise((resolve, reject) => {
    let ready = false;
    const timer = setTimeout(() => reject(new Error('Python 服务启动超时，请检查虚拟环境。')), 20000);
    worker = spawn(python, ['-u', '-m', 'backend.worker'], {
      cwd: ROOT, env: { ...process.env, PYTHONUNBUFFERED: '1' }, stdio: ['pipe', 'pipe', 'pipe'],
    });
    worker.on('error', () => {
      clearTimeout(timer);
      reject(new Error('无法启动 Python，请先按 README 安装依赖。'));
    });
    createInterface({ input: worker.stdout }).on('line', (line) => {
      let message;
      try { message = JSON.parse(line); } catch { return; }
      if (message.event === 'ready') {
        ready = true;
        clearTimeout(timer);
        resolve();
      } else if (message.event === 'index-progress') {
        if (window && !window.isDestroyed()) window.webContents.send('index-progress', message.data);
      } else if (pending.has(message.id)) {
        const request = pending.get(message.id);
        pending.delete(message.id);
        clearTimeout(request.timer);
        if (message.error) request.reject(new Error(message.error));
        else request.resolve(message.result);
      }
    });
    worker.stderr.on('data', (chunk) => {
      fs.appendFile(path.join(RUNTIME, 'backend.log'), chunk).catch(() => {});
    });
    worker.on('exit', () => {
      clearTimeout(timer);
      const error = new Error('Python 服务已退出，请重新打开应用。');
      if (!ready) reject(error);
      for (const request of pending.values()) {
        clearTimeout(request.timer);
        request.reject(error);
      }
      pending.clear();
      worker = null;
    });
  });
  // The first renderer request will display startup errors.
  workerReady.catch(() => {});
}

async function request(method, payload = {}) {
  await workerReady;
  if (!worker || worker.stdin.destroyed) throw new Error('Python 服务不可用，请重启应用。');
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error('操作超时，请稍后重试。'));
    }, method === 'index' ? 30 * 60 * 1000 : 240000);
    pending.set(id, { resolve, reject, timer, timeoutMs: method === 'index' ? 30 * 60 * 1000 : 240000 });
    worker.stdin.write(`${JSON.stringify({ id, method, ...payload })}\n`, (error) => {
      if (error) {
        clearTimeout(timer);
        pending.delete(id);
        reject(new Error('无法连接 Python 服务。'));
      }
    });
  });
}

function assertSender(event) {
  if (!window || event.sender !== window.webContents || event.senderFrame?.url !== APP_URL) {
    throw new Error('不允许的请求来源。');
  }
}

async function getPhotos() {
  try {
    return JSON.parse(await fs.readFile(path.join(ROOT, 'data', 'manifest.json'), 'utf8')).photos;
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }
}

app.whenReady().then(async () => {
  await fs.mkdir(RUNTIME, { recursive: true });
  const assets = { '/index.html': 'text/html', '/styles.css': 'text/css', '/library.css': 'text/css', '/renderer.js': 'text/javascript' };
  protocol.handle('imagerag', async (request) => {
    const url = new URL(request.url);
    if (url.hostname === 'app' && assets[url.pathname]) {
      const body = await fs.readFile(path.join(ROOT, 'renderer', url.pathname.slice(1)));
      return new Response(body, { headers: { 'Content-Type': assets[url.pathname] } });
    }
    if (url.hostname === 'photos' && /^\/[a-f0-9]{16}$/.test(url.pathname)) {
      const photo = (await getPhotos()).find((item) => item.id === url.pathname.slice(1));
      if (photo) {
        const filename = url.searchParams.get('thumb') === '1' ? photo.thumbnail : photo.path;
        const resolved = path.resolve(ROOT, 'data', filename);
        const dataRoot = path.resolve(ROOT, 'data') + path.sep;
        if (resolved.startsWith(dataRoot)) {
          try { return new Response(await fs.readFile(resolved), { headers: { 'Content-Type': 'image/jpeg' } }); }
          catch { return new Response('Image not found', { status: 404 }); }
        }
      }
    }
    return new Response('Not found', { status: 404 });
  });
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  startWorker();
  ipcMain.handle('library:status', async (event) => { assertSender(event); return request('status'); });
  ipcMain.handle('library:photos', async (event) => { assertSender(event); return request('photos'); });
  ipcMain.handle('library:index', async (event) => { assertSender(event); return request('index'); });
  ipcMain.handle('library:search', async (event, query, mediaType = 'all') => {
    assertSender(event);
    if (typeof query !== 'string' || !query.trim() || query.length > 1000) throw new Error('请输入有效的图片描述。');
    if (!['all', 'photo', 'screenshot', 'illustration'].includes(mediaType)) throw new Error('无效的图片类型。');
    return request('search', { query, limit: 12, media_type: mediaType });
  });
  ipcMain.handle('library:source', async (event, id) => {
    assertSender(event);
    const photo = (await getPhotos()).find((item) => item.id === id);
    if (!photo) throw new Error('图片不存在。');
    const url = new URL(photo.source_url);
    // Only public source hosts used by this library may be opened externally.
    if (!['flickr.com', 'www.flickr.com', 'huggingface.co', 'commons.wikimedia.org'].includes(url.hostname)) throw new Error('此来源不支持直接打开。');
    url.protocol = 'https:';
    await shell.openExternal(url.href);
  });
  window = new BrowserWindow({
    width: 1320, height: 930, minWidth: 760, minHeight: 620,
    title: '拾图 · Image RAG', backgroundColor: '#f8f9fa',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event) => event.preventDefault());
  window.on('ready-to-show', () => {
    if (process.env.IMAGERAG_E2E !== '1') window.show();
  });
  await window.loadURL(APP_URL);
});

app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => {
  if (quitting) return;
  quitting = true;
  if (worker) worker.kill();
});
