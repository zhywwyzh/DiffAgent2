#!/usr/bin/env python3
# Entity: station-host
# Invoked: 根 Makefile drone-* 或操作者直接调用
"""冻结新版 L3 源码，投放到独立设备目录并观察端侧操作。"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid

L3 = Path(__file__).resolve().parents[1]
ROOT = L3.parent
ASSETS = L3 / 'bringup/k3s/real'
LOCAL = L3 / '.artifacts/drone'
WORKER = L3 / 'tools/drone-host-runtime.py'


def read_env(path):
    result = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, sep, value = line.partition('=')
            if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
                raise ValueError('配置须为 KEY=value 数据')
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            result[key] = value
    return result


def config():
    defaults = read_env(ASSETS / 'runtime.defaults.env')
    overrides = read_env(ROOT / '.local.env')
    unknown = [k for k in overrides if k.startswith('DRONE_') and k not in defaults]
    if unknown:
        raise ValueError('未知配置: ' + ', '.join(unknown))
    c = {k: overrides.get(k, v) for k, v in defaults.items()}
    missing = [k for k, v in c.items() if not v]
    if missing:
        raise ValueError('请配置 .local.env: ' + ', '.join(missing))
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', c['DRONE_SSH_TARGET']) or c['DRONE_SSH_TARGET'].startswith('-'):
        raise ValueError('DRONE_SSH_TARGET 必须为 SSH 配置别名')
    for k in ('DRONE_REMOTE_ROOT',):
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+', c[k]):
            raise ValueError(k + ' 必须为无 shell 字符的绝对路径')
    old = json.loads(c['DRONE_OLD_REMOTE_ROOTS'])
    if not isinstance(old, list) or not old or any(not isinstance(p, str) or not p.startswith('/') for p in old):
        raise ValueError('DRONE_OLD_REMOTE_ROOTS 必须是绝对路径 JSON 数组')
    for k in ('DRONE_NAMESPACE', 'DRONE_NODE'):
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,61}[a-z0-9])?', c[k]):
            raise ValueError(k + ' 名称不合法')
    if c['DRONE_NAMESPACE'] in ('default', 'kube-system', 'lx-real', 'sim'):
        raise ValueError('需要新版专用 namespace')
    if not re.fullmatch(r'real/[A-Za-z0-9_.-]+', c['DRONE_STACK_ID']):
        raise ValueError('需要独立 real/... stack 身份')
    if '@' in c['DRONE_L3_IMAGE'] and '@sha256:' not in c['DRONE_L3_IMAGE']:
        raise ValueError('镜像不得含凭据')
    for key in ('DRONE_BUILD_JOBS', 'DRONE_BUILD_TIMEOUT_S', 'DRONE_READY_TIMEOUT_S'):
        if not c[key].isdigit() or int(c[key]) < 1:
            raise ValueError(key + ' 必须是正整数')
    if not re.fullmatch(r'[1-9][0-9]*(Mi|Gi)', c['DRONE_BUILD_MEMORY']):
        raise ValueError('DRONE_BUILD_MEMORY 必须为 Mi/Gi')
    if not math.isfinite(float(c['DRONE_GROUND_Z'])):
        raise ValueError('地面高度必须有限')
    if c['DRONE_WORLD_FRAME'] != 'world' or c['DRONE_COMMAND_TOPIC'] != '/setpoint_cmd':
        raise ValueError('当前执行契约要求 world 与 /setpoint_cmd，不支持静默改名')
    for k in ('DRONE_ODOMETRY_TOPIC', 'DRONE_CLOUD_TOPIC', 'DRONE_STATE_TOPIC', 'DRONE_EXTENDED_STATE_TOPIC', 'DRONE_COMMAND_TOPIC'):
        if not re.fullmatch(r'/[A-Za-z0-9_/]+', c[k]):
            raise ValueError(k + ' 主题不合法')
    if not c['DRONE_ZENOH_ROUTER'].startswith('tcp/') or not c['DRONE_ROS_MASTER_URI'].startswith('http://'):
        raise ValueError('请显式配置 tcp/ Zenoh 与 http:// ROS master')
    return c


def atomic(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True))
    os.replace(tmp, path)


def rpc(c, action, **params):
    request = {'action': action, 'config': c, **params}
    if action == 'stage':
        request['worker_code'] = WORKER.read_text()
    encoded = base64.b64encode(json.dumps(request).encode()).decode()
    # SSH 远端 shell 仅接收固定 Python 入口和 shell-quoted base64 参数。
    cmd = ['ssh', '-oBatchMode=yes', '-oConnectTimeout=10', '--', c['DRONE_SSH_TARGET'],
           'python3 - ' + shlex.quote(encoded)]
    result = subprocess.run(cmd, input=WORKER.read_text(), text=True, stdout=subprocess.PIPE)
    if result.returncode:
        try:
            reason = json.loads(result.stdout).get('reason', '')
        except (ValueError, TypeError):
            reason = ''
        raise RuntimeError(reason or '远端请求失败或连接中断；请 drone-status 查询，不重复提交操作')
    body = json.loads(result.stdout)
    if not body.get('ok'):
        raise RuntimeError(body.get('reason', '远端拒绝'))
    return body


def inventory():
    paths = []
    for relative in ('ros_packages', 'bringup/launch', 'bringup/config', 'bringup/k3s/real'):
        paths.extend((L3 / relative).rglob('*'))
    paths.extend(L3 / p for p in ('tools/build_ego.sh', 'tools/drone-host-runtime.py'))
    result = {}
    for path in sorted(set(paths)):
        relative = path.relative_to(L3)
        if any(p in ('.git', '.artifacts', '__pycache__', 'test', 'tests') for p in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError('投放源码不接受符号链接: ' + str(relative))
        if not path.is_file() or path.suffix in ('.pyc', '.pyo'):
            continue
        result[str(relative)] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                 'mode': path.stat().st_mode & 0o777}
    return result


def sync(c):
    first = inventory()
    staging = LOCAL / ('snapshot-' + uuid.uuid4().hex)
    staging.mkdir(parents=True)
    try:
        for relative in first:
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(L3 / relative, destination)
        copied = {p: {'sha256': hashlib.sha256((staging / p).read_bytes()).hexdigest(),
                      'mode': (staging / p).stat().st_mode & 0o777} for p in first}
        if copied != first or inventory() != first:
            raise RuntimeError('冻结期间源码发生变化，请重试')
        source = hashlib.sha256(json.dumps(first, sort_keys=True).encode()).hexdigest()
        atomic(staging / 'manifest.json', first)
        upload = rpc(c, 'stage', source=source)
        destination = c['DRONE_SSH_TARGET'] + ':' + upload['path'] + '/'
        subprocess.run(['rsync', '-a', '--delete', '--protect-args', '-e', 'ssh -oBatchMode=yes -oConnectTimeout=10',
                        str(staging) + '/', destination], check=True)
        result = rpc(c, 'publish', source=source, stage=upload['stage'])
        atomic(LOCAL / 'selection.json', {'target': c['DRONE_SSH_TARGET'], 'root': c['DRONE_REMOTE_ROOT'],
                                         'source': source, 'config': c})
        return result
    finally:
        shutil.rmtree(staging)


def selected(c):
    record = json.loads((LOCAL / 'selection.json').read_text())
    if record['target'] != c['DRONE_SSH_TARGET'] or record['root'] != c['DRONE_REMOTE_ROOT'] or record['config'] != c:
        raise ValueError('目标或配置已改变，请重新 drone-sync')
    return record['source']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'sync', 'build', 'prepare', 'up', 'down', 'deploy', 'status', 'logs', 'build-cancel'))
    parser.add_argument('--previous', action='store_true', help='up 显式恢复同配置的前一成功版本')
    args = parser.parse_args()
    c = config()
    LOCAL.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (LOCAL / 'station.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'plan':
            print(json.dumps({'action': 'plan', 'target': c['DRONE_SSH_TARGET'], 'root': c['DRONE_REMOTE_ROOT'],
                              'files': list(inventory()), 'old_roots': json.loads(c['DRONE_OLD_REMOTE_ROOTS'])}, ensure_ascii=False))
            return
        if args.action in ('sync', 'prepare', 'deploy'):
            result = sync(c)
            if args.action == 'sync':
                print(json.dumps(result, ensure_ascii=False))
                return
        if args.action == 'logs':
            log = rpc(c, 'logs')
            print(log['log'])
            return
        if args.action in ('status', 'build-cancel'):
            print(json.dumps(rpc(c, args.action), ensure_ascii=False, indent=2))
            return
        if args.previous and args.action != 'up':
            raise ValueError('--previous 仅用于 up')
        source = selected(c)
        action = 'build' if args.action == 'prepare' else args.action
        result = rpc(c, 'submit', operation=action, source=source, previous=args.previous)
        operation = result['operation']
        print('远端操作 ' + operation + ' 已提交；断线后使用 make drone-status', file=sys.stderr)
        offset = 0
        while True:
            result = rpc(c, 'status', operation=operation)
            log = rpc(c, 'logs', operation=operation)['log']
            if len(log) > offset:
                print(log[offset:], end='', file=sys.stderr, flush=True)
            offset = len(log)
            atomic(LOCAL / 'last-operation.json', result)
            if result.get('state') in ('done', 'failed', 'cancelled', 'unknown'):
                print(json.dumps(result, ensure_ascii=False, indent=2))
                if result['state'] != 'done':
                    raise RuntimeError('端侧操作未成功；已保留日志与制品记录')
                break
            time.sleep(3)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
