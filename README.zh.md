# InPurity
InPurity是一个Windows服务程序，它包含一个主服务和一个守护服务，能够阻止你的电脑显示色情图片和视频，让你的大脑从多巴胺的陷阱中解脱出来，回归现实生活，当你经过了一段时间的“净化”后，你会找回纯净的内心，感受到生活的美好。
## 如何使用？
你可以直接从发布页下载安装包进行安装，安装后的目录结构如下：
```
InPurity
├── daemon_service
│   ├── _internal
│   └── daemon_service.exe
├── install_script
│   ├── _internal
│   └── install_script.exe
├── log
│   ├── certificate_installer.log
│   ├── daemon_service.log
│   ├── in_purity_proxy.log
│   ├── in_purity_service.log
│   └── mitmproxy.log
├── main_service
│   ├── _internal
│   └── main_service.exe
├── model
│   └── mobilenet_v2.onnx
├── proxy_config
│   ├── _internal
│   └── proxy_config.exe
├── run_mitmdump
│   ├── _internal
│   └── run_mitmdump.exe
└── purity.db
```
- `certificate_installer.log`：mitmproxy的证书文件将会在安装程序时自动安装到你的电脑中的.mitmproxy文件夹中，这样可以确保能够正确解析HTTPS数据，该文件中记录了安装结果。
- `daemon_service.log`：守护服务日志。
- `in_purity_proxy.log`：代理检测结果日志。
- `in_purity_service.log`：主服务日志。
- `mitmproxy.log`：mitmproxy输出日志。
- `proxy_config.exe`：当你在安装程序后，需要进行一些设置来确保能否正常使用mitmproxy。例如：如果你的电脑上已经安装过代理程序，比如：Clash等。你需要通过这个简单的程序来设置上游代理地址等等，这些设置会被保存到purity.db中。
在安装程序后，你可以通过查看Windows代理设置或直接打开一个网页查看是否正确运行，如果没有正确运行可以通过日志文件来查看问题。

## 它是如何工作的？
这个程序会安装两个服务，一个主服务，一个守护服务。
- **主服务**：
用来启动mitmproxy本地代理，本地代理收到请求时会先检查网址是否在黑名单中，如果在黑名单中直接返回，如果不在黑名单中发送请求。收到响应数据后通过mobilenet模型检测图片是否合法，如果合法正常返回，如果不合法返回错误请求，对于视频进行分帧检测。当一个网址中的非法响应达到60%时将加入黑名单中。
![pic1.png](pic1.png)
- **守护服务**：
将监听主服务状态和Windows代理设置是否变动以防止随意停止服务或关闭代理。

## 感谢
本项目使用了以下开源项目：

- **[mitmproxy](https://github.com/mitmproxy/mitmproxy)**
  An interactive TLS-capable intercepting HTTP proxy for penetration testers and software developers.

- **[Deep NN for NSFW Detection](https://github.com/GantMan/nsfw_model)**  
  Developed by Gant Laborde. A deep neural network model for detecting NSFW content.

## 开源许可
本项目采用 [MIT License](LICENSE) 开源许可。

## 贡献和二开
欢迎任何人对项目提供贡献或二次开发。