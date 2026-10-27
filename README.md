# 拾图 · Image RAG

用一句话找图片。拾图把图片和文字转换成向量，在本地计算相似度，帮你从图库里找到想要的画面。

项目包含 Android 应用和 Electron 桌面版，目前都还在开发中。

## 功能

- 用自然语言搜索图片，比如「一只趴在沙发上的猫」
- Android 支持选择一个或多个相册，再按需建立索引
- 图片向量保存在本地；已索引的图片不会在每次搜索时重新向量化
- 使用阿里云百炼 `qwen3-vl-embedding`，也可以配置兼容的请求地址

## Android 安装

从 [Releases](https://github.com/Comet966/ImageRag/releases) 下载 APK，传到手机上安装。需要 Android 8.0 或更新版本；首次安装可能需要允许浏览器或文件管理器安装应用。

这是一份用于测试的 Debug 安装包，尚未上架应用商店，也还没有在各种真机上充分测试。

## 申请 API Key

1. 登录[阿里云百炼](https://bailian.console.aliyun.com/)，按页面提示开通服务。
2. 打开 [API Key 获取说明](https://help.aliyun.com/zh/model-studio/get-api-key/)，进入密钥管理页面，选择**华北 2（北京）**地域并创建 Key。
3. 在拾图首页点右上角设置，填入 Key，点击「保存密钥」。默认请求地址可以不改。
4. 回到首页，点「选择图库」，选好想搜索的相册，然后点「建立索引」。完成后就可以输入文字搜索了。

密钥和服务地址要属于同一地域。自定义地址时，请填写兼容多模态向量 API 的**完整 HTTPS 请求地址**，不是 OpenAI 兼容接口的 Base URL。接口格式见[阿里云文档](https://help.aliyun.com/zh/model-studio/multimodal-embedding-api-reference)。

图片建索引时会上传缩小后的图片，搜索时会发送查询文字，因此会产生流量和模型用量；费用和免费额度以[百炼模型页面](https://help.aliyun.com/zh/model-studio/qwen3-vl-embedding)为准。向量和加密后的 Key 保存在手机本地；应用直连你配置的服务，请只使用可信服务和自己的 Key。阿里云不建议在移动客户端使用长期有效的 Key，请根据自己的使用场景控制密钥权限和用量。

目前索引需要保持应用打开，中断后可以重新开始；只支持按相册选择，还不能逐张选择。搜索结果只覆盖当前选中的相册和系统授权的图片。

## 桌面版开发

需要 Node.js 22.12+ 和 Python 3.12。首次运行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
npx install-electron
cp .env.example .env
```

在 `.env` 填写 `DASHSCOPE_API_KEY`，然后准备测试图库并启动：

```bash
npm run download:demo
npm run expand:demo
npm run index
npm start
```

下载脚本需要网络，建立索引会调用模型。测试图片、向量数据库和 `.env` 不包含在仓库中；复制项目时需要自行准备。

## Android 开发

用 Android Studio 打开 `android/`，安装 Android SDK 37，使用 Gradle 9.5 构建 Debug APK。详细说明见 [android/README.md](android/README.md)。

```bash
gradle assembleDebug
```

## 测试

```bash
npm test
npm run test:e2e
```

桌面端 E2E 需要准备测试图库和索引；离线验收可设置 `IMAGERAG_NO_API=1`。当前尚未完成安卓真机适配和自动化测试。

## 说明

项目仍是早期版本：搜索截图中的精确文字尚不支持独立 OCR，Android 暂无后台索引。测试图库来源包括 [Open Images](https://storage.googleapis.com/openimages/web/download_v7.html)、[ScreenSpot](https://huggingface.co/datasets/bevaya/ScreenSpot) 和 [Wikimedia Commons](https://commons.wikimedia.org/)，各素材的许可见对应来源。
