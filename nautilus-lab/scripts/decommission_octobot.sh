#!/bin/bash
# Вывод OctoBot из эксплуатации. ⚠️ НЕ ЗАПУСКАТЬ, пока Nautilus paper-контур не заменит форвард-тест.
#
# ПОЧЕМУ ЗАЩИЩЁН: 10 OctoBot-инстансов — единственный незагрязнённый форвард-источник,
# валидирующий S11. Снести их ДО того, как Nautilus paper непрерывно их заменит = потерять
# форвард-валидацию единственной выжившей стратегии. Удаляем ТОЛЬКО после verify замены.
#
# Запуск (осознанно): bash decommission_octobot.sh --i-understand
set -e
if [ "$1" != "--i-understand" ]; then
  echo "ЗАЩИТА: скрипт удалит 10+ OctoBot-сервисов и /opt/octobot/inst-*."
  echo "Это остановит форвард-тест S11. Запускать ТОЛЬКО после проверки Nautilus paper-замены."
  echo "Осознанный запуск: bash $0 --i-understand"
  exit 1
fi

echo "=== резервная копия конфигов перед удалением ==="
mkdir -p /root/octobot-backups/decommission-$(date +%Y%m%d)
cp /etc/systemd/system/octobot-*.{service,timer} /root/octobot-backups/decommission-$(date +%Y%m%d)/ 2>/dev/null || true

echo "=== остановка и отключение OctoBot-сервисов ==="
for u in $(systemctl list-units 'octobot*' --no-legend --all 2>/dev/null | awk '{print $1}'); do
  systemctl disable --now "$u" 2>/dev/null || true
  echo "  отключён $u"
done

echo "=== удаление unit-файлов ==="
rm -f /etc/systemd/system/octobot-*.service /etc/systemd/system/octobot-*.timer
rm -f /etc/systemd/system/octobot.service
systemctl daemon-reload

echo "=== удаление инстансов (озеро/движок/nautilus-lab СОХРАНЯЮТСЯ) ==="
rm -rf /opt/octobot/inst-* /opt/octobot/backtest
# НЕ трогаем: strategy-lab (движок+озеро), nautilus-lab (продукт), nautilus-venv, bot (venv если нужен nautilus? — нет, отдельный)

echo "ГОТОВО. OctoBot выведен. Проверь, что nautilus paper-контур работает: ntlab status"
