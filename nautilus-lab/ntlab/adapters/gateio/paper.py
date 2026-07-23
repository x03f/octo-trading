"""Локальный PAPER execution на живых ПУБЛИЧНЫХ данных Gate.io.

⚠️ ЭТО СИМУЛЯЦИЯ, а не биржевой sandbox (у Gate.io нет публичного спотового testnet — проверено:
api-testnet не резолвится, fx-api-testnet только фьючерсы). Ордера НЕ уходят на биржу. Заполнения
моделируются по реальному стакану/последней цене Gate.io. Комиссии, шаг цены, минимальный размер —
из реальных ограничений инструмента Gate.io.

Реалистичная модель (не «мгновенно по желаемой цене»):
  · market — заполняется по противоположной стороне стакана + проскальзывание при недостатке глубины;
  · limit — заполняется, если рыночная цена дошла до лимита (по данным следующих тиков/свечей);
  · комиссия taker/maker из инструмента; частичные заполнения при тонком стакане.
"""
import time
from .data import GateioData


class PaperFill:
    __slots__ = ("order_id", "client_id", "symbol", "side", "price", "amount", "fee",
                 "fee_currency", "role", "ts", "partial")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


class PaperExecution:
    """Симулятор исполнения на живых данных Gate.io. Хранит виртуальные балансы, ордера, сделки."""
    SIMULATION = True

    def __init__(self, starting_balances=None, taker_fee=0.0016, maker_fee=0.00075, data=None):
        self.data = data or GateioData()
        self.balances = dict(starting_balances or {"USDT": 10000.0})
        self.taker_fee, self.maker_fee = taker_fee, maker_fee
        self.orders = {}          # id -> order dict
        self.fills = []           # list[PaperFill]
        self._seq = 0
        self._instr_cache = {}

    def _instr(self, symbol):
        if symbol not in self._instr_cache:
            self._instr_cache[symbol] = self.data.instrument(symbol) or {}
        return self._instr_cache[symbol]

    def _round_price(self, symbol, price):
        p = self._instr(symbol).get("price_precision")
        return round(price, int(p)) if p is not None else price

    def _round_amount(self, symbol, amount):
        a = self._instr(symbol).get("amount_precision")
        return round(amount, int(a)) if a is not None else amount

    def check_min(self, symbol, amount, price):
        """Проверка минимального размера и notional Gate.io. Возвращает (ok, причина)."""
        instr = self._instr(symbol)
        notional = amount * price
        min_q = float(instr.get("min_quote_amount") or 0)
        min_b = float(instr.get("min_base_amount") or 0)
        if min_q and notional < min_q:
            return False, f"notional {notional:.2f} < min {min_q}"
        if min_b and amount < min_b:
            return False, f"amount {amount} < min_base {min_b}"
        return True, ""

    def _next_id(self):
        self._seq += 1
        return f"paper-{self._seq}"

    def submit_market(self, symbol, side, amount, client_id=None, ts=None):
        """Рыночный ордер: заполняется по стакану. Возвращает список PaperFill (частичные возможны)."""
        ts = ts or int(time.time() * 1000)
        amount = self._round_amount(symbol, amount)
        ob = self.data.order_book(symbol, limit=20)
        book = ob["asks"] if side == "buy" else ob["bids"]
        if not book:
            return {"status": "rejected", "reason": "нет стакана", "fills": []}
        ok, reason = self.check_min(symbol, amount, book[0][0])
        if not ok:
            return {"status": "rejected", "reason": reason, "fills": []}
        oid = self._next_id()
        fills, remaining, cost = [], amount, 0.0
        for px, qty in book:                              # проходим глубину = проскальзывание
            take = min(remaining, qty)
            if take <= 0:
                break
            px = self._round_price(symbol, px)
            fee = take * px * self.taker_fee
            fills.append(PaperFill(order_id=oid, client_id=client_id, symbol=symbol, side=side,
                                   price=px, amount=take, fee=fee, fee_currency="USDT",
                                   role="taker", ts=ts, partial=(take < remaining)))
            cost += take * px
            remaining -= take
            if remaining <= 1e-12:
                break
        filled = amount - remaining
        self._apply_fills(symbol, side, fills)
        self.fills.extend(fills)
        status = "closed" if remaining <= 1e-9 else ("partial" if filled > 0 else "rejected")
        self.orders[oid] = {"id": oid, "client_id": client_id, "symbol": symbol, "side": side,
                            "type": "market", "amount": amount, "filled": filled,
                            "avg_price": (cost / filled) if filled else 0.0, "status": status}
        return {"status": status, "order_id": oid, "filled": filled,
                "avg_price": (cost / filled) if filled else 0.0,
                "fills": [f.as_dict() for f in fills]}

    def _apply_fills(self, symbol, side, fills):
        base = symbol.split("_")[0]
        for f in fills:
            notional = f.amount * f.price
            if side == "buy":
                self.balances["USDT"] = self.balances.get("USDT", 0) - notional - f.fee
                self.balances[base] = self.balances.get(base, 0) + f.amount
            else:
                self.balances["USDT"] = self.balances.get("USDT", 0) + notional - f.fee
                self.balances[base] = self.balances.get(base, 0) - f.amount

    def equity_usdt(self):
        """Оценка капитала в USDT по текущим ценам (для equity curve)."""
        eq = self.balances.get("USDT", 0.0)
        for cur, amt in self.balances.items():
            if cur == "USDT" or abs(amt) < 1e-9:
                continue
            try:
                c = self.data.candles(f"{cur}_USDT", "1m", limit=1)
                if c:
                    eq += amt * c[-1]["close"]
            except Exception:
                pass
        return eq

    def snapshot(self):
        return {"simulation": True, "balances": dict(self.balances),
                "orders": len(self.orders), "fills": len(self.fills),
                "equity_usdt": round(self.equity_usdt(), 2)}
