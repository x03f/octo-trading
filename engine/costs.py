"""Модель костов. Дефолт под Gate: taker ~0.05-0.06%, плюс базовый слипедж.
Без костов бумажный результат — фикция (BACKTEST-METHODOLOGY)."""


class CostModel:
    def __init__(self, fee_bps=6.0, slip_bps=5.0):
        # bps = 0.01%. fee=6bps (0.06% taker Gate), slip=5bps базовый.
        self.fee_bps = fee_bps
        self.slip_bps = slip_bps
        self.rate = (fee_bps + slip_bps) / 1e4  # доля от оборота

    def cost(self, turnover):
        """turnover = Σ|Δweight| за ребаланс → доля эквити, съеденная костами."""
        return turnover * self.rate

    def __repr__(self):
        return f"CostModel(fee={self.fee_bps}bps, slip={self.slip_bps}bps, rate={self.rate:.5f})"


# пресеты
GATE_TAKER = CostModel(fee_bps=6.0, slip_bps=5.0)
GATE_MAKER = CostModel(fee_bps=2.0, slip_bps=3.0)
ZERO = CostModel(fee_bps=0.0, slip_bps=0.0)  # только для сверки с бенчмарком
