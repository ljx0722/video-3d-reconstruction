# 三维世界实验室 / 3D World Lab — 项目评估与优化建议报告

**评估日期**: 2026-08-09  
**核心技术**: lingbot-map (Geometric Context Transformer)  
**地址**: https://video2gauss.sealoshzh.site  
**仓库**: github.com/ljx0722/video-3d-reconstruction

---

## 一、项目概述

本系统基于开源项目 lingbot-map，构建了一个完整的"视频上传 → GPU 三维重建 → 浏览器自由浏览"的工作台平台。用户上传视频后，系统自动在 RTX 3090 GPU 服务器上运行前馈式神经网络推理，预测每帧的深度图和相机姿态，然后通过深度反投影生成世界坐标点云，最终导出 GLB 格式的 3D 模型在浏览器中展示。

---

## 二、架构总览

```
用户浏览器 (React + Three.js + R3F)
    │
    ▼
Sealos Ingress (自动 HTTPS)
    ├── /        → Frontend (Nginx + React SPA)
    ├── /api/*   → Backend (FastAPI + SQLite)
    └── /files/* → Backend → 本地磁盘 GLB 文件
                          │
                          ▼
                   GPU Worker (SeetaCloud RTX 3090 24GB)
                   ├── lingbot-map 推理 (GCTStream, SDPA)
                   ├── 深度→世界坐标反投影
                   ├── predictions_to_glb 导出
                   └── HTTP 回传 GLB 到 Sealos Backend
```

---

## 三、已实现功能清单

### 前端 (React + TypeScript + Three.js)

| 功能 | 状态 | 说明 |
|------|------|------|
| 视频拖放上传 | ✅ | react-dropzone，支持 MP4/MOV/AVI/MKV，最大 2GB |
| 处理进度监控 | ✅ | 圆环百分比 + 步骤指示器 + 帧数显示 |
| 3D 点云查看器 | ✅ | Three.js PointCloud，合并 200 万点，GLB 直读 |
| 全方位旋转 | ✅ | OrbitControls 无限制旋转缩放平移 |
| 方向立方体 | ✅ | GizmoHelper 右上角 XYZ 立方体 |
| 原始视频小窗 | ✅ | 左侧面板嵌入 HTML5 播放器 |
| 作业历史 | ✅ | 卡片列表 + 状态标签 + 删除确认 |
| 公司品牌 | ✅ | Header 单行：Logo + 三维世界实验室 + 上海长晴 |
| 点大小控制 | ✅ | 滑块 0.001~0.05，splat 模式自动 ×4 |
| 透明度控制 | ✅ | 滑块 0.1~1.0 |
| 着色模式 | ✅ | RGB / 高度 / 深度 / 置信度 / 单色 / 法线 6 种 |
| 高斯 splat 渲染 | ✅ | 圆形渐变纹理 + 加法混合 |
| 亮度调节 | ✅ | 0.3~2.0 滑块 |
| 体素降采样 | ✅ | 输入体素大小 → 执行 |
| 统计去噪 | ✅ | O(n) 随机邻居滤波 (K 近邻 + 标准差阈值) |
| 原始点云恢复 | ✅ | 一键恢复 |
| 包围盒裁剪 | ✅ | 6 面数值输入 + 自动适配点云范围 |
| 裁剪可视化 | ✅ | 绿色线框包围盒 |
| 距离测量 | ✅ | 点击两点 → 自动计算 |
| 网格/坐标轴 | ✅ | 各自独立开关 |
| 视图切换 | ✅ | 透视/平行 |
| 导出 | ✅ | PLY / XYZ / GLB |
| 截图 | ✅ | Canvas → PNG 下载 |
| **Potree EDL 后处理** | ✅ | Bloom + Brightness/Contrast + Noise dithering |
| **相机轨迹线** | ✅ | GLB 239 相机 → 最近邻排序 → 渐变彩色 polyline + 标签 |
| **自适应 EDL 强度** | ✅ | 0.0~1.0 滑块 |

### 后端 (GPU 推理管线)

| 功能 | 状态 | 说明 |
|------|------|------|
| 视频→帧提取 | ✅ | OpenCV，可调 FPS |
| 图像预处理 | ✅ | load_and_preprocess_images，中心裁剪 518×378，ViT 兼容 |
| GCTStream 推理 | ✅ | 流式推理，SDPA 注意力后端，8 帧规模校准 |
| 相机姿态估计 | ✅ | 4 次迭代，pose_enc→外参 (W2C)→内参 |
| W2C→C2W 转换 | ✅ | closed_form_inverse_se3_general |
| 深度→世界坐标 | ✅ | unproject_depth_map_to_point_map (官方函数) |
| **三角网 (Mesh)** | ❌ | 仅深度图输出，无 Mesh 面片 |
| **世界点直接预测** | ❌ | enable_point=False，模型未启用点预测头部 |
| GLB 导出 | ✅ | predictions_to_glb，置信度百分位阈值 10 (保留 top 90%) |
| scene_alignment | ✅ | OpenGL 坐标对齐 + 第一相机定位 |
| 相机轨迹 GLB 嵌入 | ✅ | integrate_camera_into_scene，239 个彩色锥体 |
| 空间下采样 | ✅ | stride 4，~1/16 像素 |
| **自适应点密度** | ✅ | 按场景对角线自动计算体素，5mm~5cm 区间 |
| **置信度过滤** | ✅ | depth_conf 每像素置信度过滤 top 90% |
| **天空分割** | ❌ | ONNX 模型未安装，户外场景天空点未过滤 |
| **后端 URI API** | ✅ | GPU Worker 拉取/上传 API |

---

## 四、架构评价

### 优势

1. **完整闭环**：从上传 → GPU 推理 → 3D 可视化，全自主可控
2. **严格对齐官方管线**：经两次全面审计后，所有步骤与 demo.py 一致(详见 Section 五)
3. **运算分离**：GPU 推理在外置云服务器，Sealos 只承载轻量 Web 服务，互不干扰
4. **CI/CD 全自动**：每次 push → GitHub Actions 构建 Docker → push ghcr.io → kubectl apply → Sealos 滚动更新
5. **跨平台兼容**：React SPA 支持所有主流浏览器，移动端可访问

### 弱点

1. **单 GPU 串行处理**：仅一台 RTX 3090，同时只能处理一个视频
2. **冷启动延迟**：首次推理需加载模型 (~30s)，后续作业复用模型
3. **无 Meshing 输出**：当前只输出点云，无法生成三角面片
4. **缺天空过滤**：户外视频大量天空点 → 噪声 → 需 ONNX skyseg
5. **点云去重效率**：基于 Python 字典的 WTA voxel 去重，对千万级点慢
6. **文件存储上限**：未设置 PVC 自动清理策略，长期运行可能耗尽磁盘

---

## 五、管线审计历史

| 版本 | 问题 | 发现 | 修复 |
|------|------|------|------|
| v1 | 自定义 GLB 构建 | 仅 20 keyframes + top 25% conf + 体素平均 | 替换为官方 unproject + predictions_to_glb |
| v2 | 置信度过滤过激 | 每帧 percentile 75 硬过滤 | 改为 conf_thres=10 (top 90%) |
| v3 | FlashInfer 不可用 | 容器无 nvcc/ninja | 回退 SDPA (README 称已修复 SDPA KV cache bug) |
| v4 | 体素平均造成虚影 | 取平均产生 double-image | 改为 winner-take-all (保留最高置信度点) |
| v5 | 相机轨迹未加入 | GLB 生成无相机数据 | 集成 integrate_camera_into_scene |
| v6 | 场景对齐简单 | 简单 centering | 改为 apply_scene_alignment (OpenGL + 第一相机) |
| v7 | Temp dir 累积 | 每次处理遗留 60-120MB 临时帧 | shutil.rmtree 即时清理 |

---

## 六、优化建议（按优先级排序）

### 🔴 高优先级

| # | 问题 | 影响 | 建议方案 | 预估工时 |
|---|------|------|----------|---------|
| 1 | **天空/背景点过滤缺失** | 户外视频大量天空点产生噪声，质量下降明显 | 安装 ONNX skyseg.onnx (已下载)，在 process_video 中调用 segment_sky() | 2h |
| 2 | **点云无 Mesh** | 仅点云，无法做测量/动画/物理模拟 | 集成 Poisson 或 Ball-pivoting 表面重建（Open3D/trimesh），增加 Mesh 下载选项 | 8h |
| 3 | **GPU 热启动优化** | 冷启动 30s+ 首次用户体验差 | 保持一个常驻 Worker 进程 + watchdog 自动重启 | 1h |

### 🟡 中优先级

| # | 问题 | 影响 | 建议方案 | 预估工时 |
|---|------|------|----------|---------|
| 4 | **点云去重需 GPU 加速** | 千万级点云去重耗时长（>10s） | 将 winner-take-all 逻辑移植到 PyCUDA kernel，性能 10-100x | 4h |
| 5 | **缺少环回闭合** | 长序列帧间漂移，两端可能不闭合 | 无需——lingbot-map 是前馈模型，不含 SLAM 环回闭合。若长序列严重漂移，切换到 windowed mode | —— |
| 6 | **自适应帧数选择** | 固定 fps=10，可能帧不够或过多 | 根据视频时长自动计算最优 fps，使得总帧数落在 60~320 范围 | 30min |
| 7 | **PVC 自动清理** | 旧作业的视频和 GLB 永远存留 | 增加 7 天 TTL cron job / Sealos 生命周期策略 | 2h |
| 8 | **并行 GPU 队列** | 仅 1 Worker，多用户排队 | 增加 Redis pub/sub 多 Worker 协调，支持多 GPU 横向扩展 | 4h |

### 🟢 低优先级

| # | 问题 | 影响 | 建议方案 | 预估工时 |
|---|------|------|----------|---------|
| 9 | **EDL 深度纹理增强** | 当前 EDL 通过 Bloom 模拟，非真正的逐像素深度梯度 | 实现 WebGL2 depthTexture 自定义 shader pass (Potree 原生 EDL) | 6h |
| 10 | **支持更多输入格式** | 仅支持视频，不支持图片序列/深度相机 | 增加图片序列上传 + RGBD 格式 | 3h |
| 11 | **URL 分享** | 无分享功能 | 增加 permalink 复制按钮 | 1h |
| 12 | **i18n 国际化** | 仅中文，海外用户不便 | 增加 en 语言包，按浏览器 Accept-Language 自动切换 | 2h |
| 13 | **点云格式全面导出** | 仅 PLY/XYZ/GLB | 增加 LAS, E57, PCD, OBJ 格式 | 3h |
| 14 | **移动端适配** | 左侧面板 + 工具栏在小屏上拥挤 | 响应式布局：移动端折叠侧栏 + 底部工具栏 | 4h |
| 15 | **Gaussian Splatting 支持** | 当前 splat 只是视觉模拟，不能做真正的 3DGS 渲染 | 集成 gsplat.js / antimatter15 的 WebGL 3DGS 查看器 | 16h |

---

## 七、技术栈总结

| 层 | 技术 | 版本 |
|----|------|------|
| 前端框架 | React + TypeScript + Vite + TailwindCSS | 18.3 / 5.5 / 5.4 / 3.4 |
| 3D 引擎 | Three.js + @react-three/fiber + @react-three/drei | 0.168 / 8.17 / 9.114 |
| 后处理 | @react-three/postprocessing + postprocessing | 2.19 / 6.39 |
| 状态管理 | SWR | 2.2 |
| 后端框架 | FastAPI + Uvicorn + SQLAlchemy + aiosqlite | 0.112 / 0.30 / 2.0 / 0.20 |
| ML 推理 | PyTorch + CUDA + lingbot-map | 2.5.1 / 12.1 / 0.1.0 |
| 点云处理 | trimesh + numpy + scipy | 4.12 / 2.2 / 1.15 |
| 存储 | SQLite (本地文件) + GitHub Container Registry | —— |
| CI/CD | GitHub Actions + Docker + kubectl | —— |
| 部署 | Sealos (K8s) + SeetaCloud (GPU 云) | —— |

---

## 八、性能指标

| 指标 | 值 | 说明 |
|------|-----|------|
| 推理速度 | ~4.7 FPS | RTX 3090, 518×378 分辨率, SDPA 后端 |
| 113 帧处理时间 | ~22s | 113 帧 @ 10fps 采样 |
| GPU 显存占用 | ~12.4 GB (峰值) | 模型 7.5GB + KV 缓存 + FP32 中间量 |
| GPU 模型加载 | ~30s | 冷启动，加载 + JIT 编译 |
| GLB 文件大小 | 15~32 MB | 113 帧，全分辨率点云 |
| 前端加载速度 | ~0.7s | 15MB GLB, 10.9 MB/s CDN |
| 浏览器渲染 | 60 FPS | 200 万点, RTX 3060+ 下流畅 |

---

## 九、与同类项目对比

| 项目 | 输入 | 输出 | GPU | Web | 价格 |
|------|------|------|-----|-----|------|
| **3D World Lab** | 视频 | GLB 点云 | RTX 3090 | ✅ | ~3 元/小时 |
| Luma AI (NeRF) | 视频 | 3DGS/NeRF | 云端 | ✅ | $1/模型 |
| Polycam | 拍照 | Mesh | 云端 | ✅ | 免费/订阅 |
| KIRI Engine | 拍照/视频 | 3DGS | 云端 | ✅ | 免费/订阅 |
| RealityCapture | 拍照 | Mesh | 本地 GPU | ❌ | $3750/永久 |
| COLMAP+OpenMVS | 拍照 | Mesh 点云 | 本地 | ❌ | 免费 |

**核心差异**：
- 我们是前馈模型，不做优化（无 COLMAP/BA/PnP），**速度最快但精度中等**
- Luma/KIRI 做 NeRF/3DGS 优化，**精度最高但耗时分钟级**
- Polycam/KIRI 封装了传统 SFM+MVS 管线，**输出 Mesh + 纹理，功能最全**

---

## 十、最终评价

### 整体评分：**B+ (82/100)**

| 维度 | 评分 | 评价 |
|------|------|------|
| 架构设计 | 85 | 清晰分层，前后端分离，GPU 独立，CI/CD 成熟 |
| 代码质量 | 78 | 管线经两次审计对齐官方，仍有部分遗留调试代码 |
| 3D 重建质量 | 75 | 点云密度足（2M+），但缺少天空过滤 + Mesh 输出 |
| 前端体验 | 82 | 工作台布局专业，控制工具丰富，EDL 后处理效果好 |
| 操作效率 | 80 | 上传→处理→查看 1-2 分钟，冷启动 30s 可优化 |
| 扩展性 | 78 | 单 GPU 无队列，未配备 PVC 清理策略 |

### 下一步行动建议

1. **立即**：安装 skyseg.onnx，过滤户外视频天空点
2. **本周**：增加 Mesh 输出 (Poisson 表面重建)
3. **本周**：增加 7 天 TTL 自动清理
4. **本月**：增加 LAS/E57 格式导出 + URL 分享
5. **本月**：研究 3DGS 实时渲染集成 (gsplat.js / WebGL)
