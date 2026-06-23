"""Analytics surface computed on the Black-76 (futures) engine.

Ported and re-grounded from the merge blueprint: OI analytics, IV/vol context, GEX + zero-gamma
flip, and the market-implied distribution. Everything here consumes the normalized `OptionChain`
and computes on the FUTURES price via `oip.quant.black76` — never on spot.
"""
