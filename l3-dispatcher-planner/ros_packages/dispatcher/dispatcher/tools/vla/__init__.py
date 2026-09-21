"""VLA 技能家族：navigation.vla_nav 的技能与宿主端口（航点执行器形态）。

waypoint_world 由站端解算后随调用下行（「累积点云 + 位姿@帧时戳 +
VLM bbox」在 station 完成），机上只消费 rpc 参数并执行；本家族不含
几何模块（见 l3-skill-contract.spec.md §10）。
"""
