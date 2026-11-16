const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
    isElectron: true,
    openPlanFileDialog: () => ipcRenderer.invoke('dialog:openPlanFile')
});
