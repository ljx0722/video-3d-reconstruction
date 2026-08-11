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

不要下载 `master` 的浮动版本。将 Worker 和 Mesh 模块下载到同一个临时发布目录，先自检，再原子切换：

```bash
set -euo pipefail
PY=/root/miniconda3/bin/python
RELEASE_DIR="/root/video3d-releases/${RELEASE_SHA}"
mkdir -p "$RELEASE_DIR"

curl -fsSL -o "$RELEASE_DIR/gpu_server.py" \
  "https://raw.githubusercontent.com/ljx0722/video-3d-reconstruction/${RELEASE_SHA}/gpu_worker/gpu_server.py"
curl -fsSL -o "$RELEASE_DIR/mesh_builder.py" \
  "https://raw.githubusercontent.com/ljx0722/video-3d-reconstruction/${RELEASE_SHA}/gpu_worker/mesh_builder.py"

$PY -m py_compile "$RELEASE_DIR/gpu_server.py" "$RELEASE_DIR/mesh_builder.py"
$PY "$RELEASE_DIR/mesh_builder.py" --self-test
ln -sfn "$RELEASE_DIR" /root/video3d-current
```

只有上述命令全部成功后才重启 Worker。`GPU_SECRET` 应从实例上的 root-only 环境文件或平台 secret 注入：

```bash
set -a
. /root/.config/video3d-worker.env
set +a

pkill -f '/root/video3d-current/gpu_server.py' 2>/dev/null || true
nohup /root/miniconda3/bin/python /root/video3d-current/gpu_server.py \
  >/root/gpu_worker.log 2>&1 &
sleep 5
pgrep -af 'video3d-current/gpu_server.py'
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

线框不是额外生成的文件；前端使用同一个 `result_mesh.glb` 构造 `THREE.WireframeGeometry`。
