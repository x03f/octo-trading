"""Реестр стратегий-нот портфеля (STRATEGY-SUITE.md). Пополняется по мере реализации.
Weight-стратегии (generate→[T×N]) в REGISTRY; Carry/Ensemble имеют свой интерфейс run()."""
from .turtle import Turtle
from .gridmr import GridMR
from .pairs import Pairs
from .fluger import Fluger
from .carry import Carry
from .ensemble import Ensemble
from .squeeze import Squeeze
from .rotation import Rotation
from .absorption import Absorption
from .newlisting import NewListing

REGISTRY = {
    "turtle": Turtle, "S4": Turtle,
    "mayatnik": GridMR, "S5": GridMR,
    "pairs": Pairs, "S3": Pairs,
    "fluger": Fluger, "S1": Fluger,
    "squeeze": Squeeze, "S8": Squeeze,
    "absorption": Absorption, "S12": Absorption,
    "newlisting": NewListing, "S11": NewListing,
    "rotation": Rotation, "S9": Rotation,
}

__all__ = ["REGISTRY", "Turtle", "GridMR", "Pairs", "Fluger", "Carry", "Ensemble", "Squeeze", "Rotation", "Absorption", "NewListing"]
