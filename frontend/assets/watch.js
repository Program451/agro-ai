/* Bounded, non-overlapping cloud observations. stop() prevents future requests. */
(function (root) {
  'use strict';
  class AgroWatch {
    constructor(take, status, clock = globalThis) {
      this.take = take; this.status = status; this.clock = clock;
      this.running = false; this.sequence = 0;
    }
    start() {
      if (this.running) return;
      this.running = true;
      const sequence = ++this.sequence;
      this.failures = 0;
      this.expiry = this.clock.setTimeout(() => this.stop('Сеанс 30 минут завершён. Можно начать новый.'), 30 * 60000);
      this.tick(sequence);
    }
    stop(message = 'AI-наблюдение остановлено. Уже отправленный запрос может сохраниться в журнале.') {
      this.running = false; this.sequence++;
      this.clock.clearTimeout(this.timer); this.clock.clearTimeout(this.expiry);
      this.controller?.abort();
      this.status(message);
    }
    async tick(sequence) {
      if (!this.running || sequence !== this.sequence) return;
      this.controller = new AbortController();
      try {
        await this.take(this.controller.signal);
        this.failures = 0;
      } catch (error) {
        if (!this.running || sequence !== this.sequence) return;
        this.failures++;
        if ([401, 403, 503].includes(error.status) || this.failures >= 3 || error.quota) {
          this.stop(error.message + ' Наблюдение приостановлено.');
          return;
        }
        this.status(error.message + ' Повторим через 30 секунд.');
      }
      if (this.running && sequence === this.sequence) {
        // Wait after completion as well: never overlap paid requests or exceed the server rate.
        this.timer = this.clock.setTimeout(() => this.tick(sequence), 31000);
      }
    }
  }
  root.AgroWatch = AgroWatch;
  if (typeof module !== 'undefined') module.exports = AgroWatch;
})(globalThis);
