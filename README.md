# 智谱画图 (astrbot_plugin_zhipu_draw)

让 AstrBot 用智谱 CogView 免费画图。不用显卡，不用中转，一个 API Key 就能跑。

- `/画图 一只橘猫趴在窗台上晒太阳，水彩风` —— 手动出图
- 聊天里直接说「帮我画一只柴犬」—— Bot 判断该画时自己调用 `generate_image` 工具

## 为什么用它

| | 智谱 CogView-3-Flash | 本地 SD / ComfyUI | 各类逆向接口 |
|---|---|---|---|
| 需要显卡 | 否 | 是 | 否 |
| 需要付费 | 否（免费额度） | 电费 | 不稳定 |
| 接口稳定性 | 官方 API | 看部署 | 随时失效 |
| 出图速度 | 10–60 秒 | 看机器 | 看运气 |

代价是免费版会在图片右下角打「AI生成」水印，尺寸只有固定的几档。

## 安装

### 方式一：插件市场

在 AstrBot WebUI 的「插件」页面搜索「智谱画图」安装。

### 方式二：手动

```bash
cd /AstrBot/data/plugins
git clone https://github.com/Tree/astrbot_plugin_zhipu_draw.git
```

装完重启 AstrBot。

## 配置

1. 打开 [bigmodel.cn](https://bigmodel.cn) 注册（手机号即可）
2. 右上角头像 → API Keys → 新建，复制整串（形如 `xxxxxxxx.yyyyyyyy`）
3. AstrBot WebUI → 插件 → 智谱画图 → 配置，把 Key 填进「智谱 API Key」
4. 保存，重启或在聊天里发一条 `/画图 测试` 验证

### 配置项

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `api_key` | 空 | 必填，智谱开放平台的 Key |
| `model` | `cogview-3-flash` | 免费模型；`cogview-4` 效果更好但收费 |
| `size` | `1024x1024` | 支持 7 档尺寸，非法值自动回退 |
| `quality` | `standard` | 仅 `cogview-4` 生效，可设 `hd` |
| `timeout` | `120` | 单次请求超时（秒） |
| `allow_auto_draw` | `true` | 关掉后只能手动 `/画图` |
| `cooldown_seconds` | `10` | 同一会话的冷却时间，防刷屏 |
| `max_concurrency` | `2` | 同时进行中的画图任务上限 |
| `max_keep_files` | `200` | 本地图片保留数量，超出删最旧的 |
| `save_dir` | `plugin_data/astrbot_plugin_zhipu_draw` | 图片存放目录 |

## 使用

```
/画图 雨夜的赛博朋克街道，一只柴犬正在奔跑，霓虹灯反射在积水上
/画图 竖版海报，樱花树下的少女，浅粉色，胶片质感
```

支持的尺寸（选竖版时把 `size` 改成 `768x1344` 之类）：

`1024x1024` `768x1344` `864x1152` `1344x768` `1152x864` `1440x720` `720x1440`

别名：`/绘图`、`/画画`、`/智谱画图`、`/cogview`

## 常见问题

**401 / 1001 / 1002：Key 不对**
确认复制完整，智谱的 Key 是「32 位 ID + 一个点 + 16 位密钥」，只复制前半段会 401。

**1301：内容审核没过**
换个说法。真人明星、版权角色名、性暗示、暴力血腥的描述容易被拦。

**1303 / 1304：并发或额度超了**
把 `max_concurrency` 改成 1，或等一会儿再试。免费额度有每日上限。

**图片有水印**
`cogview-3-flash` 是免费的，右下角固定带「AI生成」。想要无水印要换付费模型。

**为什么图是 jpg 而不是 png**
智谱有时返回 JPEG，插件按文件头判断真实格式再存盘，扩展名和内容一致。

## 开发

```
astrbot_plugin_zhipu_draw/
├── main.py             # 指令、LLM 工具、接口调用
├── metadata.yaml       # 插件元信息
├── _conf_schema.json   # WebUI 配置项
├── README.md
├── CHANGELOG.md
└── LICENSE
```

没有第三方依赖，只用 `aiohttp`（AstrBot 自带）。

## 许可证

MIT
