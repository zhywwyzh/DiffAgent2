"""共享执行平面：跨家族共享动作端口、家族宿主与装配。

契约归属 l3-dispatcher/execution-seam；ports.py 承载跨家族共享动作端口，
skill_host.py 实现各家族宿主端口，composition.py 为装配入口。
航点下发的执行实现归使用它的工具家族（tools/<family>/waypoint.py）。
"""
