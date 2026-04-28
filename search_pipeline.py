# Task 4 — Hybrid Search Pipeline (FastAPI)
# L1(32D, top200) → L2(128D, top80) → L3(1024D+sparse, top40) → RRF → top30 → Rerank → Top3
# 全部 DB 调用使用 Mock 函数，手写 RRF 算法（k=60）

# TODO: implement search router, layered recall, RRF, cross-encoder rerank
