"""VLA 工具家族：navigation.vla_nav 的技能、几何与宿主端口。

几何保留在本目录（tools/vla/geometry.py，vla 专用、不通用共享）；
感知原语本体归 dispatcher/perception/base_policy.py，经宿主注入到达。
机上不做 VLM/bbox 推理：grounded detection 由 station 单次接地下发，
drone 侧只消费 rpc 参数（见 l3-skill-contract.spec.md §10）。
"""
