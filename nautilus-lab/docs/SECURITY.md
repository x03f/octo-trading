# Безопасный доступ к дашборду и защита live-действий

## Сетевая модель (проверено)
- `ntlab-api` слушает **только 127.0.0.1:5020** (`ss -tlnp` → `LISTEN 127.0.0.1:5020`).
  Порт НЕ доступен извне; торговые и административные API публично недоступны без туннеля/прокси.
- Никакой другой сервис не проксирует :5020 наружу (Caddy-сайта для него нет).

## Способ 1 (рекомендуемый): SSH-туннель
```bash
ssh -L 5020:127.0.0.1:5020 root@<SERVER_IP>
# затем открыть в браузере: http://127.0.0.1:5020
```
Дашборд доступен только внутри SSH-сессии; наружу порт закрыт.

## Способ 2 (опционально): HTTPS reverse proxy + Authelia
Authelia и Caddy на сервере уже активны (используются другими панелями). Чтобы вынести дашборд
под тем же SSO, добавить сайт в Caddyfile (доступ только после аутентификации Authelia):
```caddy
nautilus.kodlabs.ru {
    forward_auth 127.0.0.1:9091 {
        uri /api/verify?rd=https://auth.kodlabs.ru
        copy_headers Remote-User Remote-Groups Remote-Email
    }
    reverse_proxy 127.0.0.1:5020
}
```
После этого дашборд доступен по HTTPS только аутентифицированным пользователям.

## Защита live-действий (проверка прав)
- Реальные ордера заблокированы многофакторно (`ntlab/nautilus/safety.py`): runtime=live +
  `NTLAB_LIVE_ENABLED=true` + файл-подтверждение `LIVE_CONFIRMED`.
- API-мутации — только paper/sandbox (симуляция). Эндпойнт `POST /api/portfolio/create` с
  `mode=live` возвращает **403**, пока не совпали все три фактора (`_live_guard`).
- `POST /api/emergency-stop` в тестовом контуре подтверждает `live_allowed=False`; с боевыми
  ключами вызовет `GateioExecution.emergency_stop` (отмена всех ордеров + выключение live).
- Секреты (ключи Gate.io/LLM) — только через env/secrets, в git не коммитятся.
