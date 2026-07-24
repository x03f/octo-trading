"""Единый интерфейс к LLM-советникам (Claude / OpenAI) + детерминированный советник без ключей.

Без ключа платформа работает в режиме DeterministicAdvisor — это позволяет тестировать ВЕСЬ
адаптивный цикл (диагностика → рекомендация → автовалидация → решение) в backtest/shadow БЕЗ
внешних вызовов и затрат. Реальный LLM подключается вводом ключа в secrets.
"""
import json, time, hashlib
from .schema import StrategyStats, Recommendation

SYSTEM_PROMPT = (
    "Ты — риск-консультант количественной торговой платформы. Тебе дают срез состояния "
    "детерминированной стратегии. Ты НЕ управляешь торговлей — ты советник. Оцени рыночный режим "
    "и предложи изменения параметров ТОЛЬКО в пределах допустимых диапазонов. Любое предложение "
    "будет автоматически проверено бэктестом до применения; не уверен — рекомендуй keep. "
    "Отвечай СТРОГО валидным JSON по схеме Recommendation, без пояснений вне JSON."
)


def _input_hash(stats: StrategyStats) -> str:
    payload = json.dumps(stats.model_dump(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class DeterministicAdvisor:
    """Советник без LLM: правила на месте нейросети. Для тестов цикла и как безопасный дефолт.
    Логика намеренно КОНСЕРВАТИВНА — предлагает изменения только при явной деградации."""
    provider = "deterministic"
    model = "rules-v1"

    def advise(self, stats: StrategyStats) -> Recommendation:
        sh = stats.sharpe if stats.sharpe is not None else 0.0
        dd = abs(stats.max_drawdown)
        vol = stats.volatility or 0.0
        regime = "unknown"
        rs = stats.regime_signals or {}
        if rs.get("trend", 0) > 0.15:
            regime = "trend_up"
        elif rs.get("trend", 0) < -0.15:
            regime = "trend_down"
        elif vol > (rs.get("vol_ref", vol) or vol) * 1.5:
            regime = "high_vol"
        else:
            regime = "range"
        # решение: пауза при большой просадке, иначе keep (консервативно — не дёргать без нужды)
        if dd > 0.25 or sh < -0.5:
            decision = "pause"
            expl = f"Просадка {dd*100:.0f}% / Sharpe {sh:+.2f} — деградация, рекомендую наблюдение."
        else:
            decision = "keep"
            expl = "Статистика в норме, режим не требует изменений."
        return Recommendation(
            market_regime=regime, confidence=0.55,
            regime_change_explanation=expl, param_changes=[],
            expected_effect="Сохранение конфигурации / снижение риска.",
            invalidation_signals=["Sharpe восстановился > 0", "просадка < 15%"],
            ttl_hours=24, extra_experiments=[], decision=decision)


class LLMAdvisor:
    """Реальный LLM (anthropic/openai). Требует ключа. Возвращает валидированную Recommendation."""
    def __init__(self, provider: str, api_key: str, model: str):
        self.provider = provider
        self.model = model
        self._key = api_key

    def advise(self, stats: StrategyStats) -> Recommendation:
        user = ("Срез стратегии (JSON):\n" + json.dumps(stats.model_dump(), ensure_ascii=False, default=str)
                + "\n\nВерни строго JSON Recommendation.")
        raw = self._call(user)
        data = json.loads(raw)
        return Recommendation.model_validate(data)   # строгая валидация; кинет при несоответствии

    def _call(self, user: str) -> str:
        import httpx
        if self.provider == "anthropic":
            r = httpx.post("https://api.anthropic.com/v1/messages", timeout=60,
                           headers={"x-api-key": self._key, "anthropic-version": "2023-06-01",
                                    "content-type": "application/json"},
                           json={"model": self.model, "max_tokens": 1024, "system": SYSTEM_PROMPT,
                                 "messages": [{"role": "user", "content": user}]})
            r.raise_for_status()
            return r.json()["content"][0]["text"]
        if self.provider == "openai":
            r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=60,
                           headers={"Authorization": f"Bearer {self._key}", "content-type": "application/json"},
                           json={"model": self.model, "response_format": {"type": "json_object"},
                                 "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                              {"role": "user", "content": user}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        raise ValueError(f"неизвестный провайдер {self.provider}")




class MockAdvisor:
    """Mock LLM: возвращает валидную Recommendation с КОНКРЕТНЫМ предложением параметра (для E2E
    цикла применения — в отличие от DeterministicAdvisor, который консервативно держит keep).
    Стоимость/токены имитируются для проверки учёта расходов."""
    provider = "mock-llm"
    model = "mock-v1"

    def __init__(self, propose_param=None, propose_value=None):
        self.propose_param = propose_param
        self.propose_value = propose_value

    def advise(self, stats):
        from .schema import Recommendation, ParamChange
        changes = []
        if self.propose_param and self.propose_param in stats.current_params:
            changes = [ParamChange(name=self.propose_param,
                                   current=stats.current_params[self.propose_param],
                                   recommended=self.propose_value,
                                   reason="mock: подстройка под режим")]
        return Recommendation(
            market_regime="range", confidence=0.7,
            regime_change_explanation="mock анализ режима",
            param_changes=changes,
            expected_effect="mock: улучшение риск-профиля",
            invalidation_signals=["mock"], ttl_hours=24,
            decision="test_new" if changes else "keep")

    @staticmethod
    def estimate_cost(tokens_in=2000, tokens_out=500):
        # оценка стоимости запроса (для журнала расходов); mock-тариф
        return round(tokens_in / 1e6 * 3.0 + tokens_out / 1e6 * 15.0, 6)


def make_advisor(settings):
    """Фабрика: реальный LLM если есть ключ, иначе детерминированный (тесты/безопасный дефолт)."""
    if settings.LLM_PROVIDER == "anthropic" and settings.ANTHROPIC_API_KEY:
        return LLMAdvisor("anthropic", settings.ANTHROPIC_API_KEY, "claude-opus-4-8")
    if settings.LLM_PROVIDER == "openai" and settings.OPENAI_API_KEY:
        return LLMAdvisor("openai", settings.OPENAI_API_KEY, "gpt-4o")
    if settings.LLM_PROVIDER == "mock":
        return MockAdvisor()
    return DeterministicAdvisor()
