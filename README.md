# InPurity
The Chinese version of this document is available [here](README.zh.md).

InPurity is a Windows service application to block porn pictures and videos. It consists of a main service and a guardian service that stops your computer from displaying pornographic images and videos, freeing your brain from the dopamine trap and returning you to real life. After a period of "cleansing", you'll be able to find the purity of your heart and feel the beauty of life.

## How to use it?
You can install it by downloading the installation package directly from the release page and selecting the directory where you want to install it. The directory structure after installation is as follows:
```
InPurity
├── daemon_service
│   ├── _internal
│   └── daemon_service.exe
├── gui
│   ├── _internal
│   └── gui.exe
├── install_script
│   ├── _internal
│   └── install_script.exe
├── log
│   ├── archive
│   ├── daemon_service_yyyymmdd.log
│   ├── gui_yyyymmdd.log
│   ├── in_purity_yyyymmdd_.log
│   ├── log_manager_yyyymmdd.log
│   ├── main_service_yyyymmdd.log
│   └── mitmproxy_yyyymmdd.log
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
├── icon.ico
└── purity.db
```

Let me explain what you need to know about the file:

`daemon_service.log`: Logs for the daemon service.

`gui.log`: Logs for start gui.

`in_purity.log`: Logs for proxy detection results.

`log_manager.log`: Logs for log manager.

`main_service.log`: Logs for the main service.

`mitmproxy.log`: Logs output from mitmproxy.

`proxy_config.exe`: After running the installer, you may need to configure some settings to ensure mitmproxy works correctly. For example, if you already have a proxy program installed on your computer, such as Clash, you can use this simple program to set the upstream proxy address and other configurations. These settings are saved in `purity.db`.

After installation, you can check if the program is running correctly by looking at the Windows proxy settings or simply opening a webpage. If it is not functioning as expected, you can use the log files to troubleshoot the issue.

## How does it work?
This program installs two services: a main service and a daemon service.

- **Main Service**:  
  The main service starts the local mitmproxy proxy. When the local proxy receives a request, it first checks if the URL is in the blacklist. If it is, the request is blocked immediately. If it is not, the request is forwarded. Once a response is received, the program uses the MobileNet model to analyze images in the response to determine if they are appropriate. If the content is appropriate, the response is returned as normal. If not, an error response is sent back. ~~For video content, the program performs frame-by-frame analysis.~~ If 60% or more of the responses from a particular URL are deemed inappropriate, the URL is added to the blacklist.
![pic1.png](pic1.png)

- **Daemon Service**:  
  The daemon service monitors the status of the main service and checks for changes to the Windows proxy settings to prevent the service from being stopped or the proxy from being disabled unexpectedly.

## Thanks
This project makes use of the following open-source project:

- **[mitmproxy](https://github.com/mitmproxy/mitmproxy)**
  An interactive TLS-capable intercepting HTTP proxy for penetration testers and software developers.

- **[Deep NN for NSFW Detection](https://github.com/GantMan/nsfw_model)**  
  Developed by Gant Laborde. A deep neural network model for detecting NSFW content.

## License
This project is licensed under the [MIT License](LICENSE).

## Contributing and Development
We warmly welcome contributions and encourage developers to build upon this project! Whether you want to fix bugs, suggest new features, improve documentation, or adapt the project for your own needs, your input is greatly appreciated. 