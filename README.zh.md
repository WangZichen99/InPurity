# InPurity
InPurity是一个Windows服务程序，它包含一个主服务和一个守护服务，能够阻止你的电脑显示色情图片，让你的大脑从多巴胺的陷阱中解脱出来，回归现实生活，当你经过了一段时间的"净化"后，你会找回纯净的内心，感受到生活的美好。

## InPurity是如何工作的？
这个程序会安装两个服务，一个主服务，一个守护服务。

- **主服务**：
用来启动mitmproxy本地代理，本地代理收到请求时会先检查网址是否在黑名单中，如果在黑名单中直接返回，如果不在黑名单中发送请求。收到响应数据后通过mobilenet模型检测图片是否合法，如果合法正常返回，如果不合法返回错误请求，~~对于视频进行分帧检测~~。当一个网址中的非法响应达到60%时将加入黑名单中。
![pic1.png](pic1.png)

- **守护服务**：
将监听主服务状态和Windows代理设置是否变动以防止随意停止服务或关闭代理。

## 致谢
本项目使用了以下开源项目：

- **[mitmproxy](https://github.com/mitmproxy/mitmproxy)**
  An interactive TLS-capable intercepting HTTP proxy for penetration testers and software developers.

- **[Deep NN for NSFW Detection](https://github.com/GantMan/nsfw_model)**  
  Developed by Gant Laborde. A deep neural network model for detecting NSFW content.

## 开源许可
本项目采用 [MIT License](LICENSE) 开源许可。

## 贡献和二开
欢迎任何人对项目提供贡献或二次开发。
