# AutoDL GPU Worker

生产重建 Worker 运行在外部 AutoDL/算力云实例上，而不是 Sealos。GitHub Actions 只发布 frontend/backend，因此每次修改 `gpu_worker/` 后必须单独更新该实例。

## 安全前置条件

1. 曾经提交到仓库历史中的 SSH 密码必须先在平台控制台轮换；从 Git 删除文件不能撤销已经泄露的凭据。
2. 优先配置 SSH key，并在 `~/.ssh/known_hosts` 中固定服务端 host key。不要使用 `AutoAddPolicy`，不要把密码、私钥、`GPU_SECRET` 写进仓库或 shell history。
3. Sealos backend 和 Worker 必须配置相同的非默认 `GPU_SECRET`。通过平台 Secret/进程环境注入，不要写入 manifest 明文。

以下命令中的变量均应由当前 shell 或安全的 secret manager 提供：

```bash
export GPU_HOST='<rotated-host>'
export GPU_PORT='<rotated-port>'
export GPU_USER='root'
export RELEASE_SHA='<git-commit-sha>'
```

## 首次准备

SSH 登录实例后，使用已有的 lingbot-map conda 环境：

```bash
PY=/root/miniconda3/bin/python
PIP=/root/miniconda3/bin/pip

curl -fsSL -o /root/requirements.autodl.txt \
  "https://raw.githubusercontent.com/ljx0722/video-3d-reconstruction/${RELEASE_SHA}/gpu_worker/requirements.autodl.txt"
$PIP install --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
  --extra-index-url https://mirrors.aliyun.com/pypi/simple \
  --trusted-host pypi.tuna.tsinghua.edu.cn \
  --trusted-host mirrors.aliyun.com \
  --requirement /root/requirements.autodl.txt

$PY - <<'PY'
import open3d
import torch
print('Open3D:', open3d.__version__)
print('CUDA:', torch.cuda.is_available())
PY
```

lingbot-map 和 checkpoint 的推荐位置保持为：

- `/root/lingbot-map`
- `/root/lingbot-map/checkpoint/lingbot-map.pt`

## 固定 commit 发布

不要下载 `master` 的浮动版本。将 Worker、Mesh 模块和本次使用的 `lingbot_map.vis.glb_export` 放进同一个固定提交发布目录；新建独立 venv 复用现有 Torch/CUDA，先自检，再原子切换：

```bash
set -euo pipefail
PY=/root/miniconda3/bin/python
RELEASE_DIR="/root/video3d-releases/${RELEASE_SHA}"
VENV="/root/video3d-venvs/${RELEASE_SHA}"
mkdir -p "$RELEASE_DIR/lingbot_map/vis" /root/video3d-venvs

curl -fsSL -o "$RELEASE_DIR/gpu_server.py" \
  "https://raw.githubusercontent.com/ljx0722/video-3d-reconstruction/${RELEASE_SHA}/gpu_worker/gpu_server.py"
curl -fsSL -o "$RELEASE_DIR/mesh_builder.py" \
  "https://raw.githubusercontent.com/ljx0722/video-3d-reconstruction/${RELEASE_SHA}/gpu_worker/mesh_builder.py"
curl -fsSL -o "$RELEASE_DIR/requirements.autodl.txt" \
  "https://raw.githubusercontent.com/ljx0722/video-3d-reconstruction/${RELEASE_SHA}/gpu_worker/requirements.autodl.txt"
curl -fsSL -o "$RELEASE_DIR/lingbot_map/vis/glb_export.py" \
  "https://raw.githubusercontent.com/ljx0722/video-3d-reconstruction/${RELEASE_SHA}/lingbot-map-vendor/lingbot_map/vis/glb_export.py"
printf '%s\n' 'from pkgutil import extend_path' '__path__ = extend_path(__path__, __name__)' \
  > "$RELEASE_DIR/lingbot_map/__init__.py"
printf '%s\n' 'from pkgutil import extend_path' '__path__ = extend_path(__path__, __name__)' \
  > "$RELEASE_DIR/lingbot_map/vis/__init__.py"

if [ ! -x "$VENV/bin/python" ]; then
  $PY -m venv --system-site-packages "$VENV"
fi
"$VENV/bin/pip" install --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
  --trusted-host pypi.tuna.tsinghua.edu.cn \
  --requirement "$RELEASE_DIR/requirements.autodl.txt"

"$VENV/bin/python" -m py_compile \
  "$RELEASE_DIR/gpu_server.py" \
  "$RELEASE_DIR/mesh_builder.py" \
  "$RELEASE_DIR/lingbot_map/vis/glb_export.py"
PYTHONPATH="$RELEASE_DIR:/root/lingbot-map" \
  "$VENV/bin/python" "$RELEASE_DIR/mesh_builder.py" --self-test
PYTHONPATH="$RELEASE_DIR:/root/lingbot-map" "$VENV/bin/python" - <<'PY'
from lingbot_map.vis.glb_export import compute_scene_alignment
print('artifact-v2 alignment import:', compute_scene_alignment.__name__)
PY
```

只有上述命令全部成功后才切换。先保存上一版 release，再原子更新当前 release；运行时根据 release 目录名选择同 SHA 的 venv，避免代码与环境错配：

```bash
PREVIOUS_RELEASE="$(readlink -f /root/video3d-current 2>/dev/null || true)"
if [ -n "$PREVIOUS_RELEASE" ] && [ "$PREVIOUS_RELEASE" != "$RELEASE_DIR" ]; then
  ln -sfn "$PREVIOUS_RELEASE" /root/video3d-previous
fi
ln -sfn "$RELEASE_DIR" /root/video3d-current.next
mv -Tf /root/video3d-current.next /root/video3d-current
```

`GPU_SECRET` 应从实例上的 root-only 环境文件或平台 secret 注入。下面的切换会精确停止旧 Worker，验证新进程进入轮询；若失败，则自动恢复上一版代码和同 SHA venv：

```bash
set -euo pipefail
set -a
. /root/.config/video3d-worker.env
set +a

start_release() {
  local release="$1"
  local sha="${release##*/}"
  local venv="/root/video3d-venvs/${sha}"
  test -x "$venv/bin/python"
  nohup env PYTHONPATH="$release:/root/lingbot-map" \
    "$venv/bin/python" "$release/gpu_server.py" \
    >/root/gpu_worker.log 2>&1 &
  local pid=$!
  printf '%s\n' "$pid" >/root/gpu_worker.pid
  sleep 5
  kill -0 "$pid" 2>/dev/null && grep -q 'GPU Worker ready' /root/gpu_worker.log
}

mapfile -t OLD_PIDS < <(pgrep -f '/root/video3d-(current|releases)(/[^ ]*)?/[g]pu_server.py' || true)
for pid in "${OLD_PIDS[@]}"; do
  kill "$pid"
done

ACTIVE_RELEASE="$(readlink -f /root/video3d-current)"
if ! start_release "$ACTIVE_RELEASE"; then
  FAILED_PID="$(cat /root/gpu_worker.pid 2>/dev/null || true)"
  if [ -n "$FAILED_PID" ]; then
    kill "$FAILED_PID" 2>/dev/null || true
  fi
  cp /root/gpu_worker.log "/root/gpu_worker.failed-${RELEASE_SHA}.log" 2>/dev/null || true
  ROLLBACK_RELEASE="$(readlink -f /root/video3d-previous 2>/dev/null || true)"
  if [ -n "$ROLLBACK_RELEASE" ]; then
    ln -sfn "$ROLLBACK_RELEASE" /root/video3d-current.next
    mv -Tf /root/video3d-current.next /root/video3d-current
    start_release "$ROLLBACK_RELEASE" || true
  fi
  exit 1
fi

pgrep -af '/root/video3d-(current|releases)(/[^ ]*)?/[g]pu_server.py'
tail -50 /root/gpu_worker.log
```

`/root/.config/video3d-worker.env` 权限必须为 `0600`，至少包含：

```text
MODEL_PATH=/root/lingbot-map/checkpoint/lingbot-map.pt
SEALOS_BACKEND_URL=https://video2gauss.sealoshzh.site
GPU_SECRET=<same-secret-as-sealos>
```

## 发布验收

1. `pgrep` 只返回一个 Worker 进程。
2. 日志启动后无 401，能持续轮询 pending API。
3. `mesh_builder.py --self-test` 输出 Open3D 版本、顶点数和三角面数。
4. 提交一个新视频后，日志依次出现 `Mesh input`、`Mesh downsample`、`Mesh built`、`GPU mesh saved`。
5. 线上 API 的作业响应为 `mesh_available: true`，且下面两个请求均为 200：

```bash
curl -I "https://video2gauss.sealoshzh.site/files/<job-id>/result.glb"
curl -I "https://video2gauss.sealoshzh.site/files/<job-id>/result_mesh.glb"
```

结构线不是额外生成的文件；前端使用同一个 `result_mesh.glb` 的实体表面和 `THREE.EdgesGeometry` 显示边界与明显折痕。
