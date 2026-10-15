#!/usr/bin/env python3
# Entity: drone-host
# Invoked: station-host-drone.py 经 SSH 引导；版本化绝对路径由 systemd 执行
"""设备侧独立工作空间的投放、编译和 L3 生命周期。"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import subprocess
import sys
import time
import uuid

OWNER_KEY = 'diffagent.io/workspace'


def command(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, stdout=subprocess.PIPE, **kwargs).stdout


def atomic(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(body, sort_keys=True, ensure_ascii=False))
    temporary.chmod(0o600)
    os.replace(temporary, path)


def load(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def overlap(a, b):
    return a == b or a in b.parents or b in a.parents


def physical(path):
    # mountinfo 的 root + 相对 mountpoint 路径能识别 bind mount 的目录别名。
    matches = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        unescape = lambda s: re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), s)
        mount = Path(unescape(fields[4]))
        if path == mount or mount in path.parents:
            matches.append((len(mount.parts), fields[2], Path(unescape(fields[3])) / path.relative_to(mount)))
    if not matches:
        raise RuntimeError('无法核对挂载来源')
    _, device, location = max(matches)
    return device, location


class Runtime:
    def __init__(self, request):
        self.request = request
        self.c = request['config']
        self.root = Path(self.c['DRONE_REMOTE_ROOT'])
        if not self.root.is_absolute() or self.root != self.root.resolve() or self.root in (Path('/'), Path.home()):
            raise RuntimeError('新版根目录不合法或包含路径别名')
        old_roots = json.loads(self.c['DRONE_OLD_REMOTE_ROOTS'])
        if not old_roots:
            raise RuntimeError('必须登记旧版远端保护目录')
        for value in old_roots:
            old = Path(value)
            if not old.is_absolute() or not old.is_dir() or old != old.resolve():
                raise RuntimeError('旧版保护目录缺失或包含路径别名')
            a, b = physical(self.root), physical(old)
            if overlap(self.root, old) or (a[0] == b[0] and overlap(a[1], b[1])):
                raise RuntimeError('新旧工作空间重合或嵌套，拒绝操作')
        self.owner = hashlib.sha256(str(self.root).encode()).hexdigest()[:16]
        marker = self.root / 'state/owner.json'
        if marker.exists():
            if load(marker) != {'owner': self.owner, 'root': str(self.root)}:
                raise RuntimeError('目录所有权不匹配')
        else:
            if self.request['action'] != 'stage':
                raise RuntimeError('新版工作空间尚未登记，请先 sync')
            self.root.mkdir(parents=True, exist_ok=True)
            # 以根目录 flock 保护首次登记，不能先在未知非空目录创建锁文件。
            fd = os.open(str(self.root), os.O_RDONLY | os.O_DIRECTORY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if marker.exists():
                    if load(marker) != {'owner': self.owner, 'root': str(self.root)}:
                        raise RuntimeError('并发登记冲突')
                elif any(self.root.iterdir()):
                    raise RuntimeError('不能接管未知非空目录')
                else:
                    atomic(marker, {'owner': self.owner, 'root': str(self.root)})
            finally:
                os.close(fd)
        if self.root.stat().st_uid != os.getuid():
            raise RuntimeError('必须以新版工作空间所有者执行')
        # 不接受内部目录被替换为链接或跨挂载目录。
        for name in ('control', 'config', 'staging', 'releases', 'builds', 'state', 'cache'):
            path = self.root / name
            if path.exists() and (path.is_symlink() or physical(path)[0] != physical(self.root)[0] or
                                  physical(path)[1] != physical(self.root)[1] / name):
                raise RuntimeError('新版子目录存在挂载别名')
            path.mkdir(exist_ok=True)
        self.ns = self.c['DRONE_NAMESPACE']
        self.kubectl = None

    def lock(self, blocking=False):
        lock = (self.root / 'state/operation.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return lock

    def verify_source(self, source):
        path = self.root / 'releases' / source
        manifest = load(path / 'manifest.json')
        if not manifest or hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest() != source:
            raise RuntimeError('已发布源码清单不匹配')
        for relative, item in manifest.items():
            file = path / relative
            if file.is_symlink() or file.resolve() != file or hashlib.sha256(file.read_bytes()).hexdigest() != item['sha256'] or file.stat().st_mode & 0o777 != item['mode']:
                raise RuntimeError('已发布源码被修改: ' + relative)
        if {str(p.relative_to(path)) for p in path.rglob('*') if p.is_file() and p != path / 'manifest.json'} != set(manifest):
            raise RuntimeError('已发布源码文件集合改变')

    def artifacts(self, attempt):
        work = self.root / 'builds' / attempt / 'work'
        result = {}
        for file in sorted(work.rglob('*')):
            if file.is_symlink():
                result[str(file.relative_to(work))] = {'link': os.readlink(file)}
            elif file.is_file():
                result[str(file.relative_to(work))] = {'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                                                        'mode': file.stat().st_mode & 0o777}
        return result

    def kube(self, *args, data=None):
        if self.kubectl is None:
            for prefix in (['kubectl'], ['sudo', '-n', 'k3s', 'kubectl']):
                try:
                    command(prefix + ['get', '--raw=/readyz'], stderr=subprocess.DEVNULL)
                    self.kubectl = prefix
                    break
                except (OSError, subprocess.CalledProcessError):
                    pass
            if self.kubectl is None:
                raise RuntimeError('k3s API 不可用')
        return command(self.kubectl + list(args), input=json.dumps(data) if data is not None else None)

    def get(self, kind, name):
        raw = self.kube('-n', self.ns, 'get', kind, name, '--ignore-not-found', '-o', 'json')
        return json.loads(raw) if raw.strip() else None

    def own(self, obj):
        if obj['metadata'].get('labels', {}).get(OWNER_KEY) != self.owner:
            raise RuntimeError('资源不属于新版工作空间')
        return obj

    def delete(self, kind, name):
        obj = self.get(kind, name)
        if not obj:
            return
        self.own(obj)
        plural = {'job': 'jobs', 'deployment': 'deployments'}[kind]
        group = 'batch/v1' if kind == 'job' else 'apps/v1'
        uri = '/apis/' + group + '/namespaces/' + self.ns + '/' + plural + '/' + name
        self.kube('delete', '--raw', uri, '-f', '-', data={
            'apiVersion': 'v1', 'kind': 'DeleteOptions', 'propagationPolicy': 'Foreground',
            'preconditions': {'uid': obj['metadata']['uid']}})
        deadline = time.monotonic() + 90
        while self.get(kind, name):
            if time.monotonic() > deadline:
                raise RuntimeError('资源退出未确认，保留状态')
            time.sleep(1)

    def namespace(self):
        obj = self.get('namespace', self.ns)
        if obj:
            self.own(obj)
        else:
            self.kube('create', '-f', '-', data={'apiVersion': 'v1', 'kind': 'Namespace',
                'metadata': {'name': self.ns, 'labels': {OWNER_KEY: self.owner}}})
        node = json.loads(self.kube('get', 'node', self.c['DRONE_NODE'], '-o', 'json'))
        if platform.machine() not in ('arm64', 'aarch64') or node['status']['nodeInfo']['architecture'] != 'arm64':
            raise RuntimeError('需要本设备原生 ARM64 节点')
        local = set(command(['hostname', '-I']).split())
        if not any(a['address'] in local for a in node['status']['addresses'] if a['type'] in ('InternalIP', 'ExternalIP')):
            raise RuntimeError('k3s 节点不是当前设备')

    def environment(self):
        return {'ROS_MASTER_URI': self.c['DRONE_ROS_MASTER_URI'], 'ROS_IP': self.c['DRONE_ROS_IP'],
                'LX_STACK_ID': self.c['DRONE_STACK_ID'], 'ZENOH_ROUTER': self.c['DRONE_ZENOH_ROUTER'],
                **{k: v for k, v in self.c.items() if k.startswith('DRONE_')}}

    def unit_state(self, unit):
        result = subprocess.run(['systemctl', 'show', unit, '--property=ActiveState', '--value'],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return result.stdout.strip() if result.returncode == 0 else 'unknown'

    @staticmethod
    def summary(record):
        if not record:
            return record
        return {key: value for key, value in record.items() if key not in ('artifacts', 'config')}

    def shell(self, body, built=False):
        # 删除镜像继承的旧 overlay；只保留明确系统环境和新版环境。
        prefix = 'source /opt/ros/noetic/setup.bash; '
        if built:
            prefix += 'source /work/l3/devel/setup.bash; '
        return ['/usr/bin/env', '-i', 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                'HOME=/tmp', 'LANG=C.UTF-8'] + [k + '=' + v for k, v in self.environment().items()] + [
                '/bin/bash', '--noprofile', '--norc', '-ec', prefix + body]

    def pod(self, source, attempt, image, body, build=False):
        release = self.root / 'releases' / source
        work = self.root / 'builds' / attempt / 'work'
        return {'nodeName': self.c['DRONE_NODE'], 'nodeSelector': {'kubernetes.io/arch': 'arm64'},
                'hostNetwork': True, 'dnsPolicy': 'ClusterFirstWithHostNet', 'restartPolicy': 'Never',
                'securityContext': {'runAsUser': os.getuid(), 'runAsGroup': os.getgid()},
                'containers': [{'name': 'l3', 'image': image, 'imagePullPolicy': 'IfNotPresent',
                    'command': self.shell(body, built=not build),
                    'securityContext': {'allowPrivilegeEscalation': False},
                    'volumeMounts': [{'name': 'source', 'mountPath': '/source/l3', 'readOnly': True},
                                     {'name': 'work', 'mountPath': '/work/l3', 'readOnly': not build},
                                     {'name': 'deployment', 'mountPath': '/source/deployment', 'readOnly': True}],
                    'resources': {'requests': {'memory': '256Mi'},
                                  'limits': {'memory': self.c['DRONE_BUILD_MEMORY']}}}],
                'volumes': [{'name': 'source', 'hostPath': {'path': str(release / 'drone_projects/l3-dispatcher-planner'), 'type': 'Directory'}},
                            {'name': 'work', 'hostPath': {'path': str(work), 'type': 'Directory'}},
                            {'name': 'deployment', 'hostPath': {'path': str(release / 'deployment'), 'type': 'Directory'}}]}

    def probe(self, source, image, action, attempt=None):
        built = attempt is not None
        name = 'probe-' + uuid.uuid4().hex[:12]
        if attempt is None:
            attempt = 'probe-' + name
            (self.root / 'builds' / attempt / 'work').mkdir(parents=True)
        pod = self.pod(source, attempt, image,
                       '/usr/bin/python3 /source/deployment/k3s/real/runtime_probe_ros.py ' + action,
                       build=True)
        pod['containers'][0]['command'] = self.shell(
            '/usr/bin/python3 /source/deployment/k3s/real/runtime_probe_ros.py ' + action, built=built)
        pod['containers'][0]['volumeMounts'][1]['readOnly'] = True
        pod['activeDeadlineSeconds'] = 30
        self.kube('create', '-f', '-', data={'apiVersion': 'v1', 'kind': 'Pod',
                   'metadata': {'name': name, 'namespace': self.ns, 'labels': {OWNER_KEY: self.owner}}, 'spec': pod})
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                obj = self.own(self.get('pod', name))
                if obj['status']['phase'] in ('Succeeded', 'Failed'):
                    raw = self.kube('-n', self.ns, 'logs', name)
                    print(raw, flush=True)
                    if obj['status']['phase'] != 'Succeeded':
                        raise RuntimeError('设备前置检查失败: ' + raw[-2000:])
                    return json.loads(raw.splitlines()[-1])
                time.sleep(1)
            raise RuntimeError('设备探针超时')
        finally:
            obj = self.get('pod', name)
            if obj:
                self.own(obj)
                self.kube('delete', '--raw', '/api/v1/namespaces/' + self.ns + '/pods/' + name, '-f', '-',
                          data={'apiVersion': 'v1', 'kind': 'DeleteOptions', 'preconditions': {'uid': obj['metadata']['uid']}})

    def image(self):
        image = self.c['DRONE_L3_IMAGE']
        # 由设备 containerd 解析、锁定实际摘要，复用已有镜像存储。
        command(['sudo', '-n', 'k3s', 'crictl', 'pull', image])
        detail = json.loads(command(['sudo', '-n', 'k3s', 'crictl', 'inspecti', image]))
        digests = detail['status'].get('repoDigests', [])
        if not digests or '@sha256:' not in digests[0]:
            raise RuntimeError('不能确定镜像摘要')
        return digests[0]

    def maintenance(self, source, image):
        return self.probe(source, image, 'maintenance')

    def build(self, source, image, operation):
        if self.get('deployment', 'new-l3'):
            raise RuntimeError('新版 L3 仍运行，请先 down 或使用 deploy')
        self.probe(source, image, 'conflicts')
        self.maintenance(source, image)
        mem = int(re.search(r'MemAvailable:\s+(\d+)', Path('/proc/meminfo').read_text())[1]) * 1024
        budget = self.c['DRONE_BUILD_MEMORY']
        requested = int(budget[:-2]) * (1024 ** (3 if budget.endswith('Gi') else 2))
        if mem < requested + 512 * 1024 ** 2 or int(self.c['DRONE_BUILD_JOBS']) > len(os.sched_getaffinity(0)):
            raise RuntimeError('设备剩余内存或 CPU 并发预算不足')
        if __import__('shutil').disk_usage(self.root).free < 2 * 1024 ** 3:
            raise RuntimeError('设备磁盘不足 2 GiB，请显式清理无引用历史')
        attempt = operation
        directory = self.root / 'builds' / attempt
        (directory / 'work').mkdir(parents=True)
        name = 'compile-' + attempt
        body = 'export L3_BUILD_JOBS=' + shlex.quote(self.c['DRONE_BUILD_JOBS']) + '; bash /source/l3/tools/build_ego.sh /work/l3; '
        body += 'test -x /work/l3/devel/lib/ego_planner/ego_planner_node; test -f /work/l3/devel/setup.bash; '
        body += 'source /work/l3/devel/setup.bash; /usr/bin/python3 /source/deployment/k3s/real/runtime_probe_ros.py dependencies'
        pod = self.pod(source, attempt, image, body, build=True)
        spec = json.loads((self.root / 'releases' / source / 'deployment/k3s/real/compile.job.yaml').read_text())
        spec['metadata'] = {'name': name, 'namespace': self.ns, 'labels': {OWNER_KEY: self.owner}}
        spec['spec'].update(activeDeadlineSeconds=int(self.c['DRONE_BUILD_TIMEOUT_S']),
                            template={'metadata': {'labels': {OWNER_KEY: self.owner}}, 'spec': pod})
        self.kube('create', '-f', '-', data=spec)
        job = self.own(self.get('job', name))
        atomic(directory / 'record.json', {'state': 'building', 'source': source, 'image': image, 'config': self.c,
                                         'job': name, 'uid': job['metadata']['uid']})
        deadline = time.monotonic() + int(self.c['DRONE_BUILD_TIMEOUT_S']) + 60
        exit_code = None
        last_maintenance = time.monotonic()
        try:
            while time.monotonic() < deadline:
                if (self.root / 'state' / ('cancel-' + operation)).exists():
                    self.delete('job', name)
                    raise RuntimeError('编译已显式取消')
                if time.monotonic() - last_maintenance > 20:
                    try:
                        self.maintenance(source, image)
                    except Exception:
                        self.delete('job', name)
                        raise RuntimeError('编译期间维护状态失效，已终止本次 Job')
                    last_maintenance = time.monotonic()
                job = self.own(self.get('job', name))
                pods = json.loads(self.kube('-n', self.ns, 'get', 'pods', '-l', 'job-name=' + name, '-o', 'json'))['items']
                if pods:
                    pod_obj = self.own(pods[0])
                    try:
                        log = self.kube('-n', self.ns, 'logs', pod_obj['metadata']['name'])
                        (directory / 'compile.log').write_text(log)
                    except subprocess.CalledProcessError:
                        pass
                    statuses = pod_obj['status'].get('containerStatuses', [])
                    terminated = statuses[0].get('state', {}).get('terminated') if statuses else None
                    if terminated:
                        exit_code = terminated['exitCode']
                        break
                if job['status'].get('failed'):
                    raise RuntimeError('编译 Job 失败，查看 Pod 与 compile.log')
                time.sleep(2)
            if exit_code != 0:
                raise RuntimeError('编译未成功，容器退出码=' + str(exit_code))
            self.verify_source(source)
            self.maintenance(source, image)
            record = load(directory / 'record.json')
            record.update(state='built', exit_code=exit_code, attempt=attempt, artifacts=self.artifacts(attempt))
            atomic(directory / 'record.json', record)
            atomic(self.root / 'state/candidate.json', record)
            return record
        except Exception:
            # 活动 Job 超时或 worker 异常后仍禁止后继操作；显式取消可清理。
            record = load(directory / 'record.json')
            record.update(state='failed', exit_code=exit_code)
            atomic(directory / 'record.json', record)
            raise

    def down(self, source, image):
        obj = self.get('deployment', 'new-l3')
        if not obj:
            return
        self.own(obj)
        active = load(self.root / 'state/active.json')
        if not active or active['config'] != self.c:
            raise RuntimeError('活动配置不同，请恢复原配置后关闭')
        self.maintenance(source, image)
        pods = json.loads(self.kube('-n', self.ns, 'get', 'pods', '-l', 'app=new-l3', '-o', 'json'))['items']
        if len(pods) != 1:
            raise RuntimeError('无法唯一确认运行实例，拒绝停止')
        self.own(pods[0])
        output = self.kube('-n', self.ns, 'exec', pods[0]['metadata']['name'], '--',
                           *self.shell('/usr/bin/python3 /source/deployment/k3s/real/runtime_probe_ros.py shutdown', built=True))
        print(output, flush=True)
        self.delete('deployment', 'new-l3')
        atomic(self.root / 'state/previous.json', active)
        (self.root / 'state/active.json').unlink()

    def up(self, source, image):
        record = load(self.root / 'state/candidate.json')
        if not record or record['state'] != 'built' or record['source'] != source or record['config'] != self.c or record['image'] != image:
            raise RuntimeError('没有匹配源码、配置和镜像的成功制品')
        self.verify_source(source)
        if self.artifacts(record['attempt']) != record['artifacts']:
            raise RuntimeError('成功编译产物已被修改，拒绝启动')
        if self.get('deployment', 'new-l3'):
            raise RuntimeError('L3 已运行；切换版本请显式 deploy')
        self.maintenance(source, image)
        self.probe(source, image, 'conflicts')
        self.probe(source, image, 'inputs', record['attempt'])
        body = 'exec roslaunch /source/l3/bringup/launch/basic_flight.launch realworld_experiment:=true '
        for key, argument in (('DRONE_GROUND_Z', 'ground_z'), ('DRONE_ODOMETRY_TOPIC', 'odometry_topic'), ('DRONE_CLOUD_TOPIC', 'cloud_topic')):
            body += shlex.quote(argument + ':=' + self.c[key]) + ' '
        pod = self.pod(source, record['attempt'], image, body)
        pod['restartPolicy'] = 'Always'
        spec = json.loads((self.root / 'releases' / source / 'deployment/k3s/real/l3.deployment.yaml').read_text())
        spec['metadata'] = {'name': 'new-l3', 'namespace': self.ns, 'labels': {OWNER_KEY: self.owner}}
        container = pod['containers'][0]
        container['readinessProbe'] = {'exec': {'command': self.shell('/usr/bin/python3 /source/deployment/k3s/real/runtime_probe_ros.py ready', built=True)},
                                       'periodSeconds': 10, 'timeoutSeconds': 20, 'failureThreshold': 3}
        spec['spec']['template'] = {'metadata': {'labels': {'app': 'new-l3', OWNER_KEY: self.owner}}, 'spec': pod}
        self.kube('create', '-f', '-', data=spec)
        # 即使启动超时也登记活动版本，后续 down 使用其原配置；不冒称已停止。
        previous = load(self.root / 'state/previous.json')
        atomic(self.root / 'state/active.json', record)
        try:
            self.kube('-n', self.ns, 'rollout', 'status', 'deployment/new-l3',
                      '--timeout=' + self.c['DRONE_READY_TIMEOUT_S'] + 's')
            self.maintenance(source, image)
        except Exception:
            try:
                self.down(source, image)
                if previous:
                    atomic(self.root / 'state/previous.json', previous)
            except Exception as error:
                print('启动失败且未能确认安全关闭，保留资源与 active 记录: ' + str(error), flush=True)
            raise
        return record

    def worker(self, operation):
        path = self.root / 'state' / (operation + '.json')
        record = load(path)
        try:
            with self.lock(blocking=True):
                self.namespace()
                # 遗留非终态编译必须先对账，不依赖旧进程是否还持有锁。
                jobs = json.loads(self.kube('-n', self.ns, 'get', 'jobs', '-o', 'json'))['items']
                if any(j['metadata'].get('labels', {}).get(OWNER_KEY) == self.owner and not
                       any(c.get('type') in ('Complete', 'Failed') and c.get('status') == 'True' for c in j.get('status', {}).get('conditions', [])) for j in jobs):
                    raise RuntimeError('仍有非终态编译 Job，请查询或显式取消')
                image = self.image()
                source = record['source']
                self.verify_source(source)
                if record['operation'] in ('down', 'deploy'):
                    self.down(source, image)
                if record['operation'] in ('build', 'deploy'):
                    self.build(source, image, operation)
                if record['operation'] in ('up', 'deploy'):
                    if (self.root / 'state' / ('cancel-' + operation)).exists():
                        raise RuntimeError('操作已取消，不启动业务')
                    self.up(source, image)
                record.update(state='done')
        except Exception as error:
            record.update(state='cancelled' if (self.root / 'state' / ('cancel-' + operation)).exists() else 'failed', reason=str(error))
            print(str(error), flush=True)
        record['finished_at'] = time.time()
        atomic(path, record)

    def handle(self):
        action = self.request['action']
        if action == 'worker':
            self.worker(self.request['operation'])
            return {'ok': True}
        if action in ('status', 'logs', 'build-cancel'):
            op = self.request.get('operation') or load(self.root / 'state/latest.json', {}).get('operation')
            if not op or not re.fullmatch(r'[0-9a-f]{24}', op):
                return {'ok': True, 'state': 'idle'}
            record = load(self.root / 'state' / (op + '.json'))
            if action == 'logs':
                log = self.root / 'state' / (op + '.log')
                compile_log = self.root / 'builds' / op / 'compile.log'
                return {'ok': True, 'log': (log.read_text() if log.exists() else '') + (compile_log.read_text() if compile_log.exists() else '')}
            if action == 'build-cancel':
                if record['operation'] not in ('build', 'deploy'):
                    raise RuntimeError('当前操作不是编译')
                atomic(self.root / 'state' / ('cancel-' + op), {'requested_at': time.time()})
                service_state = self.unit_state(record['unit'])
                if record['state'] != 'running' or service_state not in ('active', 'activating', 'reloading'):
                    with self.lock():
                        self.namespace()
                        self.delete('job', 'compile-' + op)
                        record.update(state='cancelled', reason='显式取消并完成遗留 Job 对账')
                        atomic(self.root / 'state' / (op + '.json'), record)
                return {'ok': True, 'operation': op, 'cancel_requested': True}
            if record['state'] == 'running':
                state = self.unit_state(record['unit'])
                if state not in ('active', 'activating', 'reloading'):
                    record = {**record, 'state': 'unknown', 'reason': '设备 worker 不活跃；需核对 Job，禁止重复构建'}
                    atomic(self.root / 'state' / (op + '.json'), record)
            deployment = None
            try:
                deployment = self.get('deployment', 'new-l3')
            except Exception as error:
                deployment = {'unreachable': str(error)}
            return {'ok': True, **record, 'active': self.summary(load(self.root / 'state/active.json')),
                    'candidate': self.summary(load(self.root / 'state/candidate.json')),
                    'runtime_status': deployment.get('status', deployment) if deployment else None}
        with self.lock():
            if action == 'stage':
                source_code = Path(__file__).read_text() if __file__ != '<stdin>' else None
                # 引导源码由 station 作为请求字段提供；冻结后供 systemd 绝对路径调用。
                source_code = self.request.get('worker_code', source_code)
                if not source_code:
                    raise RuntimeError('缺少设备入口源码')
                digest = hashlib.sha256(source_code.encode()).hexdigest()
                control = self.root / 'control' / digest
                control.mkdir(exist_ok=True)
                script = control / 'drone-host-runtime.py'
                if not script.exists():
                    script.write_text(source_code)
                    script.chmod(0o700)
                elif script.read_text() != source_code:
                    raise RuntimeError('控制脚本摘要冲突')
                atomic(self.root / 'state/control.json', {'path': str(script)})
                stage = uuid.uuid4().hex
                path = self.root / 'staging' / stage
                path.mkdir()
                return {'ok': True, 'stage': stage, 'path': str(path)}
            source = self.request.get('source', '')
            if not re.fullmatch(r'[0-9a-f]{64}', source):
                raise RuntimeError('源码摘要不合法')
            if action == 'publish':
                stage = self.request['stage']
                if not re.fullmatch(r'[0-9a-f]{32}', stage):
                    raise RuntimeError('staging 标识不合法')
                path = self.root / 'staging' / stage
                manifest = load(path / 'manifest.json')
                if any(p.is_symlink() for p in path.rglob('*')):
                    raise RuntimeError('投放目录不得包含符号链接')
                if hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest() != source:
                    raise RuntimeError('源码清单摘要不匹配')
                for relative, item in manifest.items():
                    if PurePosixPath(relative).is_absolute() or '..' in PurePosixPath(relative).parts:
                        raise RuntimeError('源码路径逃逸')
                    file = path / relative
                    if file.is_symlink() or file.resolve() != file or hashlib.sha256(file.read_bytes()).hexdigest() != item['sha256'] or file.stat().st_mode & 0o777 != item['mode']:
                        raise RuntimeError('源码内容或模式不匹配')
                actual = {str(p.relative_to(path)) for p in path.rglob('*') if p.is_file() and p != path / 'manifest.json'}
                if actual != set(manifest):
                    raise RuntimeError('源码文件集合不匹配')
                destination = self.root / 'releases' / source
                if destination.exists():
                    # 同摘要复用前仍核对已有内容，防止旧目录被手工修改。
                    if load(destination / 'manifest.json') != manifest or any(hashlib.sha256((destination / p).read_bytes()).hexdigest() != m['sha256'] for p, m in manifest.items()):
                        raise RuntimeError('已发布源码内容改变')
                    __import__('shutil').rmtree(path)
                else:
                    path.rename(destination)
                return {'ok': True, 'source': source}
            if action == 'submit':
                if not (self.root / 'releases' / source / 'manifest.json').is_file():
                    raise RuntimeError('源码未发布')
                operation = self.request['operation']
                if operation not in ('build', 'up', 'down', 'deploy'):
                    raise RuntimeError('未知操作')
                previous = load(self.root / 'state/latest.json', {}).get('operation')
                if previous:
                    prior = load(self.root / 'state' / (previous + '.json'))
                    if prior['state'] == 'running':
                        raise RuntimeError('已有未完成操作，请查询或取消，不重复提交')
                op = uuid.uuid4().hex[:24]
                unit = 'diffagent-' + self.owner + '-' + op
                if self.request.get('previous'):
                    previous_build = load(self.root / 'state/previous.json')
                    if operation != 'up' or not previous_build or previous_build['config'] != self.c:
                        raise RuntimeError('没有同配置的上一成功记录')
                    source = previous_build['source']
                    atomic(self.root / 'state/candidate.json', previous_build)
                record = {'operation': operation, 'source': source, 'state': 'running', 'unit': unit, 'started_at': time.time()}
                atomic(self.root / 'state' / (op + '.json'), record)
                atomic(self.root / 'state/latest.json', {'operation': op})
                script = load(self.root / 'state/control.json')['path']
                request = {'action': 'worker', 'config': self.c, 'operation': op}
                payload = base64.b64encode(json.dumps(request).encode()).decode()
                try:
                    command(['sudo', '-n', 'systemd-run', '--unit=' + unit, '--uid=' + str(os.getuid()),
                             '--gid=' + str(os.getgid()), '--property=WorkingDirectory=' + str(self.root),
                             '--property=StandardOutput=append:' + str(self.root / 'state' / (op + '.log')),
                             '--property=StandardError=inherit', '--property=TimeoutStartSec=infinity',
                             '/usr/bin/python3', script, payload])
                except Exception:
                    record.update(state='failed', reason='无法启动设备 systemd worker')
                    atomic(self.root / 'state' / (op + '.json'), record)
                    raise
                return {'ok': True, 'operation': op}
        raise RuntimeError('未知请求')


if __name__ == '__main__':
    try:
        request = json.loads(base64.b64decode(sys.argv[1]))
        result = Runtime(request).handle()
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'ok': False, 'reason': str(error)}, ensure_ascii=False))
        sys.exit(1)
