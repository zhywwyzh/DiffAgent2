# 本仓库的 k3s Unity 仿真与原生站端操作入口。
# 配置由 station-host-sim.py 从根 .local.env 解析，Makefile 不执行配置内容。
.DEFAULT_GOAL := help
.NOTPARALLEL:

REPO_ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
PYTHON ?= python3
SIM_RUN = cd "$(REPO_ROOT)" && $(PYTHON) l3-dispatcher-planner/tools/station-host-sim.py
DRONE_RUN = cd "$(REPO_ROOT)" && $(PYTHON) l3-dispatcher-planner/tools/station-host-drone.py

.PHONY: help up down status sim-render sim-prepare sim-up sim-down sim-status sim-reset
.PHONY: station-setup station-up station-stop station-status
.PHONY: drone-plan drone-sync drone-build drone-prepare drone-up drone-down drone-deploy drone-status drone-logs drone-build-cancel drone-rollback

help:
	@printf '%s\n' \
	  '首次：配置根 .local.env，make station-setup，make sim-prepare' \
	  '完整启动：make up（原 Unity 场景须处于 Play）' \
	  '完整状态：make status' \
	  '完整关闭：make down（先取消任务或急停并等待停稳）' \
	  '仅仿真：make sim-up / sim-down / sim-status / sim-reset' \
	  '仅站端：make station-up / station-stop / station-status' \
	  '仅生成清单：make sim-render' \
	  '真机：配置 DRONE_* 后，make drone-plan / drone-prepare / drone-up' \
	  '真机更新：make drone-deploy；关闭：make drone-down' \
	  '真机状态/日志：make drone-status / drone-logs'

drone-plan:
	$(DRONE_RUN) plan
drone-sync:
	$(DRONE_RUN) sync
drone-build:
	$(DRONE_RUN) build
drone-prepare:
	$(DRONE_RUN) prepare
drone-up:
	$(DRONE_RUN) up
drone-down:
	$(DRONE_RUN) down
drone-deploy:
	$(DRONE_RUN) deploy
drone-status:
	$(DRONE_RUN) status
drone-logs:
	$(DRONE_RUN) logs
drone-build-cancel:
	$(DRONE_RUN) build-cancel
drone-rollback:
	$(DRONE_RUN) up --previous

up:
	$(SIM_RUN) start

down:
	$(SIM_RUN) stop

status:
	$(SIM_RUN) status

sim-render:
	$(SIM_RUN) render

sim-prepare:
	$(SIM_RUN) prepare

sim-up:
	$(SIM_RUN) up

sim-down:
	$(SIM_RUN) down

sim-status:
	$(SIM_RUN) status

sim-reset:
	$(SIM_RUN) reset

station-setup:
	$(MAKE) -C "$(REPO_ROOT)/l4-agent" setup

station-up:
	$(SIM_RUN) station-start

station-stop:
	$(SIM_RUN) station-stop

station-status:
	$(MAKE) -C "$(REPO_ROOT)/l4-agent" l4-app status
