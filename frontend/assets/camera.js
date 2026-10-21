'use strict';
const cameraAccess = {
  async devices(askPermission = false) {
    const media = navigator.mediaDevices;
    if (!media?.getUserMedia || !media?.enumerateDevices) {
      throw new Error('Для камеры откройте сайт через HTTPS или на localhost этого ноутбука.');
    }
    let devices = (await media.enumerateDevices()).filter(device => device.kind === 'videoinput');
    // Already labelled devices need no extra capture. The default webcam may be busy in OBS.
    if (askPermission && !devices.some(device => device.label && device.deviceId)) {
      let probe;
      try {
        probe = await media.getUserMedia({ video: true, audio: false });
        devices = (await media.enumerateDevices()).filter(device => device.kind === 'videoinput');
      } finally {
        probe?.getTracks().forEach(track => track.stop());
      }
    }
    return devices;
  },
  errorMessage(error) {
    if (['NotAllowedError', 'PermissionDeniedError', 'SecurityError'].includes(error.name) ||
        /permission denied/i.test(error.message || '')) {
      return 'Доступ к камере запрещён браузером или Windows. Если сайт открыт внутри ChatGPT, скопируйте его адрес в отдельный браузер. Разрешите камеру для сайта и повторите поиск. Инструкция ниже.';
    }
    if (['NotReadableError', 'TrackStartError'].includes(error.name)) {
      return 'Камера занята или не передаёт видео. В OBS оставьте виртуальную камеру включённой, а на сайте выберите именно OBS Virtual Camera. Закройте другие приложения, использующие её.';
    }
    if (['NotFoundError', 'DevicesNotFoundError', 'OverconstrainedError'].includes(error.name)) {
      return 'Выбранная камера недоступна. Включите виртуальную камеру в OBS и нажмите «Найти камеры». Если она не появилась, перезапустите браузер.';
    }
    return 'Не удалось подключить камеру. ' + (error.message || 'Повторите поиск устройств.');
  }
};
