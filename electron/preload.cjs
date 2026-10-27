const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('imageLibrary', {
  status: () => ipcRenderer.invoke('library:status'),
  photos: () => ipcRenderer.invoke('library:photos'),
  index: () => ipcRenderer.invoke('library:index'),
  search: (query, mediaType = 'all') => ipcRenderer.invoke('library:search', query, mediaType),
  openSource: (id) => ipcRenderer.invoke('library:source', id),
  onIndexProgress: (callback) => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on('index-progress', listener);
    return () => ipcRenderer.removeListener('index-progress', listener);
  },
});
