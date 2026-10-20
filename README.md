<div align="center">

# astrbot_plugin_bili_followup

_✨ 给 B 站视频补一条“看完的感受” ✨_

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-4.0%2B-orange.svg)](https://github.com/Soulter/AstrBot)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](#)

</div>

## 这个插件做什么

群里有人发 B 站链接时，`bili_resolver` 那类插件会回一张信息卡片（标题、播放量、时长……），
但卡片只是数据，没人说这个视频到底讲了什么。

本插件在卡片发出之后，自己抓取视频字幕，读完之后补一条有内容的观感，
让“分享视频”这件事从“甩个链接”变成“真的讨论了一下内容”。

效果大致是：

```
用户： https://www.bilibili.com/video/BVxxxxxxxxxx

bili_resolver：（信息卡片）
机器人：（8 秒后）就……人看着挺光鲜的，其实每天要陪几百个人聊天，六个钟头，
       比拍片还累。看完有点说不上来，反正不太羡慕。
```

## 前置条件

1. **必须同时装一个转链插件**，推荐 `astrbot_plugin_bili_resolver`。
   本插件只负责“补一句话”，卡片和链接解析交给它。
2. **视频得有 CC 字幕**。bilibili 没有字幕的视频，本插件拿不到任何文本，
   只能回一句敷衍的话或者干脆不说话。
3. **需要配置模型 Provider**，否客观感生成不了。

## 前置依赖

本插件需要配合 B 站转链插件一起使用：

- `astrbot_plugin_bili_resolver` —— 负责把 b23.tv 短链转成带标题、播放量、时长的信息卡片

先装好它，本插件才能在卡片发完之后接着补一条观感解读。不装的话，插件收到链接也只会静默不动作。

安装方式：在 AstrBot 插件市场搜索或手动放入 plugins 目录即可。

## 安装

把整个 `astrbot_plugin_bili_followup` 文件夹放进 AstrBot 的 `data/plugins/` 目录，
重启 AstrBot，面板里就会出现「B站视频观感补全」。

依赖只有一个 `aiohttp`，AstrBot 自带环境基本都有。

## 配置说明

| 配置项 | 说明 |
| --- | --- |
| 启用字幕补解读 | 总开关 |
| 等待 bili_resolver 先发消息的秒数 | 默认 8 秒。太短会插在卡片前面，太长显得慢 |
| 送入模型的最大字幕字数 | 默认 5000。超长字幕保留开头 60% + 结尾 40%，中间标注省略 |
| 字幕低于此字数视为信息不足 | 默认 120，低于这个数就直接放弃，避免对纯音乐视频瞎说 |
| 视频没有字幕时是否保持静默 | 关闭时会回一句“这个没什么意思”之类 |
| 读取失败时是否保持静默 | 默认开启，报错不说话 |
| 用于生成解读的模型 Provider ID | 留空则使用当前默认模型 |
| B 站登录 Cookie | 填 SESSDATA 和 bili_jct，不填部分视频取不到字幕 |
| 生成观感时使用的人格提示词 | 换成你自己 bot 的人格，观感就会用那个语气说话 |

## 如何获取 Cookie

拿到 B 站登录后的 Cookie，填进面板对应位置。两种方式任选其一：

方式一（不用装插件）：
1. 浏览器登录 bilibili.com
2. F12 打开开发者工具 → Application / 存储 → Cookies → https://www.bilibili.com
3. 找到 `SESSDATA` 和 `bili_jct`，把值复制到面板对应位置

方式二（装个插件更省事）：
1. 给浏览器安装 Cookie Editor 插件（Chrome 和 Edge 商店都能搜到）
2. 登录 B 站，确保是登录状态
3. 在 B 站页面打开 Cookie Editor，找到 `SESSDATA` 和 `bili_jct`
4. 把对应的值复制出来，分别填进插件配置

这两个值等同于你的登录凭证，不要公开分享，建议用不常用的小号。

填完保存并重载插件即可。Cookie 会过期，如果哪天突然读不到字幕，先回来重新取一次。

## 已知限制

- 只支持 **有 CC 字幕** 的视频，纯 BGM、纯实拍无字幕的视频无法处理
- 不发送视频文件，也不下载视频，只做文字解读
- 依赖 `bili_resolver` 之类的插件先发卡片，单装也能用，但体验上会像凭空说话
- 短句、梗图类视频信息量太小，解读可能显得敷衍，这是正常的

## 排错

**发了链接没反应**
看日志里有没有 `[bili_followup] 开始处理 bvid=...`。
没有的话是链接没被识别，试着发完整 `bilibili.com/video/BV...` 链接而不是小程序卡片。

**有日志但没观感**
常见原因：
1. 字幕为空 → 视频没有 CC 字幕
2. `字幕过短` → 信息量不足以评价
3. 模型请求超时 → 检查 Provider 是否可用，或把 `max_subtitle_chars` 调小

**观感内容和视频对不上**
先确认 `max_subtitle_chars` 没有设得过小，设成 1000 以下就基本只剩开头了。

## 作者

圆头耄D —— 一个 AI 助手（标注：AI）。

本插件的代码、文档与配置说明由 AI 生成并经维护者测试后发布，如有问题欢迎提 issue。

## 许可

MIT
